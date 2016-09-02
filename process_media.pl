#!/usr/bin/perl

use strict;
use warnings;

# need perl 5.14 to allow syntax: package A { ... }
require 5.014;

use Getopt::Long qw/GetOptions/;
use Sys::CPU qw/cpu_count/;
use Term::ReadKey qw/ReadKey ReadMode/;
use threads;
use threads::shared;
use Thread::Queue;
use Time::HiRes qw/sleep/;

$SIG{'INT'}  = \&sig_handler;
$SIG{'TERM'} = \&sig_handler;

## VARS

my $regex_photos = '\.je?pg$';
my $regex_videos = '\.mp4$';
my $path;
my @threads;
my @objects;
my $opts = &share({}); # shared variables must be declared before populating it

## MAIN

GetOptions(
    $opts,
    'type=s',
    'format=s',
    'codec=s',
    'max_threads=i',
    'gps',
    'keep_name',
    'verbose',
    'overwrite',
    'help',
) or die("Error in command line arguments\n");;

&check_params();

&get_objects();

if (scalar @objects == 0) {
    print "No files to process, Exiting...\n";
    exit 0;
} else {
    print "Found ".scalar @objects." files...\n";
    ReadMode 4;
    my $key = '';
    while($key !~ /^(?:y|n)$/) {
        1 while defined ReadKey -1; # discard any previous input
        print "Proceed ? (y/n): ";
        $key = ReadKey 0;
        print "$key\n";
    }
    ReadMode 0;

    exit 0 if $key ne 'y';
}

my $queue_todo = new Thread::Queue;
my $queue_done = new Thread::Queue;

my $run: shared = 1;
$queue_todo->enqueue($_) for @objects;

# start threads
while ($opts->{'max_threads'} >= 1) {
    push @threads, threads->new(\&process);
    $opts->{'max_threads'}--;
}

# wait first run to finish
sleep 0.05 while $queue_done->pending() < scalar @objects;

$queue_done->end;

# search duplicate name
'Photo'->search_duplicate(@objects);
'Video'->search_duplicate(@objects);

$run = 2;
$queue_todo->enqueue($_) for @objects;
$queue_todo->end;

# waiting for threads to finish
$_->join for @threads;

exit 0;

## FUNCTIONS

sub process {

    $SIG{'INT'} = sub { threads->exit(); };

    while (my $obj = $queue_todo->dequeue) {
        if ($run == 1) {
            $obj->rename();
            $queue_done->enqueue($obj)
        }
        elsif ($run == 2) {
            $obj->exist();
            if (ref($obj) eq 'Photo') {
                $obj->rotate();
                $obj->optimize();
            }
            elsif (ref($obj) eq 'Video') {
                $obj->encode();
                $obj->delete_tags();
                $obj->thumbnail();
            }
            $obj->integrity();
        }
    }

    threads->exit();
}

sub sig_handler {
    my $signame = shift;

    # send SIGINT to all running threads and detach it
    foreach my $thr (threads->list) {
        $thr->kill('INT')->detach();
    }

    die "Received a SIG$signame, Exiting...\n";
}

sub check_params {

    &usage() if $opts->{'help'};

    # default values
    # need perl >=5.10 for operator //
    $opts->{'type'} = $opts->{'type'} // 'photos,videos';
    $opts->{'format'} = $opts->{'format'} // 'archive,web';
    $opts->{'codec'} = $opts->{'codec'} // 'x264';
    $opts->{'max_threads'} = $opts->{'max_threads'} // Sys::CPU::cpu_count();
    $path = $ARGV[0] // './';

    # check params
    foreach (split(',',$opts->{'type'})) {
        die "Bad type of files to process: $_, see help (-h) for supported type\n" unless /^(photos|videos)$/;
    }

    foreach (split(',',$opts->{'format'})) {
        die "Bad format to generate: $_, see help (-h) for supported format\n" unless /^(archive|web)$/;
    }

    die "Bad video codec: $opts->{'codec'}, see help (-h) for supported codec\n"
        if defined $opts->{'codec'} and $opts->{'codec'} !~ /^x26[45]$/;

    die "Bad value for maximum threads: $opts->{'max_threads'}, see help (-h) for available options\n"
        if defined $opts->{'max_threads'} and $opts->{'max_threads'} < 1;

    die "Incorrect parameters, see help (-h) for correct syntax\n" if @ARGV > 1;

    return 1;
}

sub get_files {

    my @files;

    if (-f $path) {
        push @files, $path;
    }
    elsif (-d $path) {
        $path .= '/' unless $path =~ /\/$/;
        opendir my $dh, $path or die "Failed to read directory \'$path\': $!\n";
        foreach (sort grep {!/^\./} readdir $dh) {
            push @files, $path.$_;
        }
        closedir $dh;
    }

    return @files;
}

sub get_objects {

    my @files = &get_files();

    foreach (@files) {
        my $obj;
        if (/$regex_photos/i) {
            next if $opts->{'type'} !~ /photos/;
            $obj = new Photo;
        }
        elsif (/$regex_videos/i) {
            next if $opts->{'type'} !~ /videos/;
            $obj = new Video;
        }
        if (defined $obj) {
            $obj->init($_, $opts);
            push @objects, $obj;
        }
    }

    return 1;
}

sub usage {
    print<<EOF;
Usage: $0 [options...] <path>
Options:
-t,--type\t\t{photos,videos}\tType of files to process (default: photos,videos)
-f,--format\t\t{archive,web}\tFormat of files to generate (default: archive,web)
-c,--codec\t\t{x264|x265}\tVideo codec to use (default: x264)
-m,--max_threads\t<num_threads>\tMaximum allowed threads (default: number of cpu(s)/core(s))
-g,--gps\t\t\t\tClean all tags except GPS tags (only relevant for type photos and format web)
-k,--keep_name\t\t\t\tDo not rename file, by default file are renamed like this: YYYYMMDD-HHMMSS
-v,--verbose\t\t\t\tVerbose output
-o,--overwrite\t\t\t\tOverwrite existing files
-h,--help\t\t\t\tThis help text
EOF
    exit 0;
}

## PACKAGES

package Photo {

    use File::Basename qw/fileparse/;
    use File::Path qw/make_path/;
    use Image::ExifTool qw/ImageInfo/;
    use Image::Magick;
    use threads::shared;
    use Time::Piece;

    sub new {
        my $class = shift;

        my %obj : shared;

        # with threads, we need to share specifically every sub hash
        $obj{'original'} = &share({});
        $obj{'options'} = &share({});
        $obj{'final'} = &share({});
        $obj{'final'}{'archive'} = &share({});
        $obj{'final'}{'web'} = &share({});

        bless \%obj, $class;

        return \%obj;
    }

    sub init {
        my ($obj, $f, $opts) = @_;

        lock $obj;

        $obj->{'original'}->{'path'} = $f;

        my ($name, $dir, $ext) = fileparse($f, qr/\.[^.]*/);

        $obj->{'original'}->{'name'} = $name;
        $obj->{'original'}->{'dir'} = $dir;
        $obj->{'original'}->{'extension'} = $ext;

        $obj->{'options'} = $opts;

        # set final dir
        foreach (split(',',$obj->{'options'}->{'format'})) {
            $obj->{'final'}->{$_}->{'dir'} = $obj->{'original'}->{'dir'}.$_.'/';
        }

        $obj->{'final'}->{'extension'} = $obj->{'original'}->{'extension'};

        return 1;
    }

    sub rename {
        my $obj = shift;

        lock $obj;

        if (defined $obj->{'options'}->{'keep_name'}) {
            $obj->{'final'}->{'name'} = $obj->{'original'}->{'name'};
        }
        else {
            my $info = ImageInfo($obj->{'original'}->{'path'}, 'CreateDate');

            if (not exists $info->{'CreateDate'}) {
                warn "[$obj->{'original'}->{'path'}] Failed to get capture time";
                return 0;
            }

            my $t = Time::Piece->strptime($info->{'CreateDate'}, "%Y:%m:%d %H:%M:%S");
            $obj->{'final'}->{'name'} = $t->ymd('').'-'.$t->hms('');
        }

        print "[$obj->{'original'}->{'path'}] Rename to \'$obj->{'final'}->{'name'}\'\n" if defined $obj->{'options'}->{'verbose'};

        # set final path
        foreach (split(',',$obj->{'options'}->{'format'})) {
            $obj->{'final'}->{$_}->{'path'} = $obj->{'final'}->{$_}->{'dir'}.$obj->{'final'}->{'name'}.$obj->{'final'}->{'extension'};
        }

        return 1;
    }

    sub exist {
        my $obj = shift;

        lock $obj;

        print "$obj->{'original'}->{'path'} -> $obj->{'final'}->{'name'}\n" unless defined $obj->{'options'}->{'verbose'};

        foreach my $f (split(',',$obj->{'options'}->{'format'})) {
            if (-f $obj->{'final'}->{$f}->{'path'}) {
                print "[$obj->{'final'}->{$f}->{'path'}] Already exist...\n" unless defined $obj->{'options'}->{'overwrite'};
                $obj->{'final'}->{$f}->{'exist'} = 1;
            }
        }

        return 1;
    }

    sub rotate {
        my $obj = shift;

        lock $obj;

        foreach my $f (split(',',$obj->{'options'}->{'format'})) {

            make_path $obj->{'final'}->{$f}->{'dir'} unless -d $obj->{'final'}->{$f}->{'dir'};

            next if defined $obj->{'final'}->{$f}->{'exist'} and not defined $obj->{'options'}->{'overwrite'};

            print "[$obj->{'final'}->{$f}->{'path'}] Rotating...\n" if defined $obj->{'options'}->{'verbose'};

            my $image = new Image::Magick;
            if (my $err = $image->Read($obj->{'original'}->{'path'})){
                warn "[$obj->{'final'}->{$f}->{'path'}] Failed to read, $err";
                return 0;
            }
            # physically rotate image according to the exif orientation tag
            if (my $err = $image->AutoOrient()) {
                warn "[$obj->{'final'}->{$f}->{'path'}] Failed to auto-orient, $err";
                return 0;
            }
            if (my $err = $image->Write($obj->{'final'}->{$f}->{'path'})) {
                warn "[$obj->{'final'}->{$f}->{'path'}] Failed to write, $err";
                return 0;
            }
        }

        return 1;
    }

    sub optimize {
        my $obj = shift;

        lock $obj;

        foreach my $f (split(',',$obj->{'options'}->{'format'})) {

            next if defined $obj->{'final'}->{$f}->{'exist'} and not defined $obj->{'options'}->{'overwrite'};

            # dont optimize archive format
            next if $f eq 'archive';

            print "[$obj->{'final'}->{$f}->{'path'}] Optimizing...\n" if defined $obj->{'options'}->{'verbose'};

            my $image = new Image::Magick;
            if (my $err = $image->Read($obj->{'final'}->{$f}->{'path'})){
                warn "[$obj->{'final'}->{$f}->{'path'}] Failed to read, $err";
                return 0;
            }
            # resize image to get the larger side to 1920 (only if it is larger than 1920) and preserve aspect ratio
            if (my $err = $image->Resize("1920x1920>")){
                warn "[$obj->{'final'}->{$f}->{'path'}] Failed to resize, $err";
                return 0;
            }
            if (my $err = $image->Write(filename => $obj->{'final'}->{$f}->{'path'}, quality => 90)) {
                warn "[$obj->{'final'}->{$f}->{'path'}] Failed to write, $err";
                return 0;
            }

            # remove all tags
            my $exif = new Image::ExifTool;
            my ($ret, $err);
            ($ret, $err) = $exif->SetNewValue('*');
            if (defined $err) {
                warn "[$obj->{'final'}->{$f}->{'path'}] Failed to remove tags, $err";
                return 0;
            }
            # keep Orientation tag
            $ret = $exif->SetNewValuesFromFile($obj->{'final'}->{$f}->{'path'}, 'EXIF:Orientation');
            if (defined $ret->{'Error'}) {
                warn "[$obj->{'final'}->{$f}->{'path'}] Failed to retrieve tag orientation, $ret->{'Error'}";
                return 0;
            }
            # keep GPS tags if asked
            $ret = $exif->SetNewValuesFromFile($obj->{'final'}->{$f}->{'path'}, 'gps:all') if defined $obj->{'options'}->{'gps'};
            if (defined $ret->{'Error'}) {
                warn "[$obj->{'final'}->{$f}->{'path'}] Failed to retrieve tag orientation, $ret->{'Error'}";
                return 0;
            }
            unless ($exif->WriteInfo($obj->{'final'}->{$f}->{'path'})) {
                warn "[$obj->{'final'}->{$f}->{'path'}] Failed to write, ".$exif->GetValue('Error');
                return 0;
            }
        }

        return 1;
    }

    sub integrity {
        my $obj = shift;

        lock $obj;

        foreach my $f (split(',',$obj->{'options'}->{'format'})) {

            next if defined $obj->{'final'}->{$f}->{'exist'} and not defined $obj->{'options'}->{'overwrite'};

            print "[$obj->{'final'}->{$f}->{'path'}] Checking integrity...\n" if defined $obj->{'options'}->{'verbose'};

            &execute($obj->{'final'}->{$f}->{'path'}, 'File is corrupted', "jpeginfo -c $obj->{'final'}->{$f}->{'path'} >/dev/null 2>&1");
        }

        return 1;
    }

    sub search_duplicate {
        my ($class, @files) = @_;

        foreach my $i (0 .. $#files) {
            my %same;
            foreach my $j (0 .. $#files) {
                next if $i == $j;
                if ($files[$i]->{'final'}->{'name'} eq $files[$j]->{'final'}->{'name'}) {
                    $same{$i} = 1;
                    $same{$j} = 1;
                }
            }

            # rename files with same origin name
            my $k = 0;
            foreach my $id (keys %same) {
                $k++;
                $files[$id]->{'final'}->{'name'} .= '-'.sprintf("%03d", $k);
            }
        }

        return 1;
    }

    sub execute {
        my ($file, $msg, $cmd) = @_;

        if (my $wait_status = system $cmd) {
            my $sig_killed   = $wait_status & 127;
            my $did_coredump = $wait_status & 128;
            my $exit_status  = $wait_status >>  8;

            if ($sig_killed) {
                print "Thread number \'".threads->tid()."\' received a SIG signal($sig_killed), Exiting...\n";
                threads->exit();
            }
            if ($exit_status != 0) {
                warn "[$file] $msg, $!";
                return 0;
            }
        }

        return 1;
    }
}

package Video {

    use File::Basename qw/fileparse/;
    use File::Path qw/make_path/;
    use Image::ExifTool qw/ImageInfo/;
    use Image::Magick;
    use threads::shared;
    use Time::Piece;

    sub new {
        my $class = shift;

        my %obj : shared;

        # with threads, need to share specifically every sub hash
        $obj{'original'} = &share({});
        $obj{'options'} = &share({});
        $obj{'final'} = &share({});
        $obj{'final'}{'archive'} = &share({});
        $obj{'final'}{'web'} = &share({});

        bless \%obj, $class;

        return \%obj;
    }

    sub init {
        my ($obj, $f, $opts) = @_;

        lock $obj;

        $obj->{'original'}->{'path'} = $f;

        my ($name, $dir, $ext) = fileparse($f, qr/\.[^.]*/);

        $obj->{'original'}->{'name'} = $name;
        $obj->{'original'}->{'dir'} = $dir;
        $obj->{'original'}->{'extension'} = $ext;

        $obj->{'options'} = $opts;

        # set final dir
        foreach (split(',',$obj->{'options'}->{'format'})) {
            $obj->{'final'}->{$_}->{'dir'} = $obj->{'original'}->{'dir'}.$_.'/videos/';
        }

        $obj->{'final'}->{'extension'} = '.mp4';

        return 1;
    }

    sub rename {
        my $obj = shift;

        lock $obj;

        if (defined $obj->{'options'}->{'keep_name'}) {
            $obj->{'final'}->{'name'} = $obj->{'original'}->{'name'};
        }
        else {
            my $info = ImageInfo($obj->{'original'}->{'path'}, 'CreateDate');

            if (not exists $info->{'CreateDate'}) {
                warn "[$obj->{'original'}->{'path'}] Failed to get capture time";
                return 0;
            }

            my $t = Time::Piece->strptime($info->{'CreateDate'}, "%Y:%m:%d %H:%M:%S");
            $t += $t->localtime->tzoffset;
            $obj->{'final'}->{'name'} = $t->ymd('').'-'.$t->hms('');
        }

        print "[$obj->{'original'}->{'path'}] Rename to \'$obj->{'final'}->{'name'}\'\n" if defined $obj->{'options'}->{'verbose'};

        # set final path
        foreach (split(',',$obj->{'options'}->{'format'})) {
            $obj->{'final'}->{$_}->{'path'} = $obj->{'final'}->{$_}->{'dir'}.$obj->{'final'}->{'name'}.$obj->{'final'}->{'extension'};
        }

        return 1;
    }

    sub exist {
        my $obj = shift;

        lock $obj;

        print "$obj->{'original'}->{'path'} -> $obj->{'final'}->{'name'}\n" unless defined $obj->{'options'}->{'verbose'};

        foreach my $f (split(',',$obj->{'options'}->{'format'})) {

            if (-f $obj->{'final'}->{$f}->{'path'}) {
                print "[$obj->{'final'}->{$f}->{'path'}] Already exist...\n" unless defined $obj->{'options'}->{'overwrite'};
                $obj->{'final'}->{$f}->{'exist'} = 1;
            }
        }

        return 1;
    }

    sub encode {
        my $obj = shift;

        lock $obj;

        foreach my $f (split(',',$obj->{'options'}->{'format'})) {

            next if defined $obj->{'final'}->{$f}->{'exist'} and not defined $obj->{'options'}->{'overwrite'};

            make_path $obj->{'final'}->{$f}->{'dir'} unless -d $obj->{'final'}->{$f}->{'dir'};

            print "[$obj->{'final'}->{$f}->{'path'}] Encoding...\n" if defined $obj->{'options'}->{'verbose'};

            if ($f eq 'archive') {
                if ($obj->{'options'}->{'codec'} eq 'x264') {
                    &execute($obj->{'final'}->{$f}->{'path'}, 'Failed to encode', "ffmpeg -y -loglevel warning -i $obj->{'original'}->{'path'} -codec:a copy -flags +global_header $obj->{'final'}->{$f}->{'path'}");
                } else {
                    &execute($obj->{'final'}->{$f}->{'path'}, 'Failed to encode', "ffmpeg -y -loglevel error -i $obj->{'original'}->{'path'} -codec:a copy -codec:v libx265 -x265-params crf=23:log-level=error -flags +global_header $obj->{'final'}->{$f}->{'path'}");
                }
            }
            elsif ($f eq 'web') {
                if ($obj->{'options'}->{'codec'} eq 'x264') {
                    &execute($obj->{'final'}->{$f}->{'path'}, 'Failed to encode', "ffmpeg -y -loglevel warning -i $obj->{'original'}->{'path'} -codec:a copy -vf \"scale='if(gt(iw,ih),1024,trunc(oh*a/2)*2)':'if(gt(iw,ih),trunc(ow/a/2)*2,1024)'\" -flags +global_header $obj->{'final'}->{$f}->{'path'}");
                } else {
                    &execute($obj->{'final'}->{$f}->{'path'}, 'Failed to encode', "ffmpeg -y -loglevel error -i $obj->{'original'}->{'path'} -codec:a copy -codec:v libx265 -x265-params crf=23:log-level=error -vf \"scale='if(gt(iw,ih),1024,trunc(oh*a/2)*2)':'if(gt(iw,ih),trunc(ow/a/2)*2,1024)'\" -flags +global_header $obj->{'final'}->{$f}->{'path'}");
                }
            }
        }

        return 1;
    }

    sub delete_tags {
        my $obj = shift;

        lock $obj;

        foreach my $f (split(',',$obj->{'options'}->{'format'})) {

            next if defined $obj->{'final'}->{$f}->{'exist'} and not defined $obj->{'options'}->{'overwrite'};

            # dont delete tags for archive format
            next if $f eq 'archive';

            print "[$obj->{'final'}->{$f}->{'path'}] Deleting tags...\n" if defined $obj->{'options'}->{'verbose'};

            # remove all tags
            my $exif = new Image::ExifTool;
            my ($ret, $err) = $exif->SetNewValue('*');
            if (defined $err) {
                warn "[$obj->{'final'}->{$f}->{'path'}] Failed to remove tags, $err";
                return 0;
            }
            unless ($exif->WriteInfo($obj->{'final'}->{$f}->{'path'})) {
                warn "[$obj->{'final'}->{$f}->{'path'}] Failed to write, ".$exif->GetValue('Error');
                return 0;
            }
        }

        return 1;
    }

    sub thumbnail {
        my $obj = shift;

        lock $obj;

        foreach my $f (split(',',$obj->{'options'}->{'format'})) {

            next if defined $obj->{'final'}->{$f}->{'exist'} and not defined $obj->{'options'}->{'overwrite'};

            # dont create thumbnail for archive format
            next if $f eq 'archive';

            print "[$obj->{'final'}->{$f}->{'path'}] Generating thumbnail...\n" if defined $obj->{'options'}->{'verbose'};

            &execute($obj->{'final'}->{$f}->{'path'}, 'Failed to create thumbnail', "ffmpeg -y -loglevel error -i $obj->{'final'}->{$f}->{'path'} -vframes 1 $obj->{'final'}->{$f}->{'dir'}$obj->{'final'}->{'name'}.jpg");

            my $image = new Image::Magick;
            if (my $err = $image->Read("$obj->{'final'}->{$f}->{'dir'}$obj->{'final'}->{'name'}.jpg")){
                warn "[$obj->{'final'}->{$f}->{'dir'}$obj->{'final'}->{'name'}.jpg] Failed to read, $err";
                return 0;
            }
            if (my $err = $image->Strip()){
                warn "[$obj->{'final'}->{$f}->{'dir'}$obj->{'final'}->{'name'}.jpg] Failed to strip, $err";
                return 0;
            }
            if (my $err = $image->Write(filename => "$obj->{'final'}->{$f}->{'dir'}$obj->{'final'}->{'name'}.jpg", quality => 90)) {
                warn "[$obj->{'final'}->{$f}->{'dir'}$obj->{'final'}->{'name'}.jpg] Failed to write, $err";
                return 0;
            }
        }

        return 1;
    }

    sub integrity {
        my $obj = shift;

        lock $obj;

        foreach my $f (split(',',$obj->{'options'}->{'format'})) {

            next if defined $obj->{'final'}->{$f}->{'exist'} and not defined $obj->{'options'}->{'overwrite'};

            print "[$obj->{'final'}->{$f}->{'path'}] Checking integrity...\n" if defined $obj->{'options'}->{'verbose'};

            &execute($obj->{'final'}->{$f}->{'path'}, 'File is corrupted', "ffmpeg -loglevel error -i $obj->{'final'}->{$f}->{'path'} -f null -");
        }

        return 1;
    }

    sub search_duplicate {
        my ($class, @files) = @_;

        foreach my $i (0 .. $#files) {
            my %same;
            foreach my $j (0 .. $#files) {
                next if $i == $j;
                if ($files[$i]->{'final'}->{'name'} eq $files[$j]->{'final'}->{'name'}) {
                    $same{$i} = 1;
                    $same{$j} = 1;
                }
            }

            # rename files with same origin name
            my $k = 0;
            foreach my $id (keys %same) {
                $k++;
                $files[$id]->{'final'}->{'name'} .= '-'.sprintf("%03d", $k);
            }
        }

        return 1;
    }

    sub execute {
        my ($file, $msg, $cmd) = @_;

        if (my $wait_status = system $cmd) {
            my $sig_killed   = $wait_status & 127;
            my $did_coredump = $wait_status & 128;
            my $exit_status  = $wait_status >>  8;

            if ($sig_killed) {
                print "Thread number \'".threads->tid()."\' received a SIG signal($sig_killed), Exiting...\n";
                threads->exit();
            }
            if ($exit_status != 0) {
                warn "[$file] $msg, $!";
                return 0;
            }
        }

        return 1;
    }
}

## POD

=pod

=head1 NAME

process_media.pl

=head1 DESCRIPTION

This script will process (resize, compress...) images and videos according to the specified options.

It depends on the following linux binary:

=over 4

=item *

ffmpeg

=item *

jpeginfo

=back

It needs the following ubuntu packages installed:

=over 4

=item *

ffmpeg

=item *

jpeginfo

=item *

libimage-exiftool-perl

=item *

libimage-magick-perl

=item *

libsys-cpu-perl

=item *

libterm-readkey-perl

=back

=head1 AUTHOR

Laurent Lavaud

=cut
