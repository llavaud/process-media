package Llavaud::Process::Media::Video;

use 5.010;

use strict;
use warnings;

use Carp qw/carp/;
use File::Basename qw/fileparse/;
use File::Copy qw/copy move/;
use File::Path qw/make_path/;
use File::Temp qw/tempfile/;
use IO::File;
use Image::ExifTool qw/ImageInfo/;
use Image::Magick;
use threads::shared;
use Time::Piece;

local $SIG{'CHLD'} = 'IGNORE';

my $ffmpeg = ($0 eq '/usr/bin/process-media') ? '/usr/bin/process-media-ffmpeg' : './ffmpeg/process-media-ffmpeg';
my $ffprobe = ($0 eq '/usr/bin/process-media') ? '/usr/bin/process-media-ffprobe' : './ffmpeg/process-media-ffprobe';

sub new {
    my $class = shift;

    my %obj : shared;

    # with threads, we need to share specifically every sub hash
    $obj{'original'} = &share({});
    $obj{'final'} = &share({});

    bless \%obj, $class;

    return \%obj;
}

sub init {
    my ($obj, $f) = @_;

    lock $obj;

    $obj->{'original'}->{'path'} = $f;

    my ($name, $dir, $ext) = fileparse($f, qr/\.[^.]*/);

    $obj->{'original'}->{'name'} = $name;
    $obj->{'original'}->{'dir'} = $dir;
    $obj->{'original'}->{'extension'} = $ext;

    # set final dir
    foreach (keys %{ $main::OPTIONS{'format'} }) {
        next if $main::OPTIONS{'format'}{$_}{'type'} ne 'video';
        $obj->{'final'}->{$_} = &share({});
        if (defined $main::OPTIONS{'format'}{$_}{'output_dir'}) {
            $main::OPTIONS{'format'}{$_}{'output_dir'} =~ s/\/+$//;
            # absolute path
            if ($main::OPTIONS{'format'}{$_}{'output_dir'} =~ /^\//) {
                $obj->{'final'}->{$_}->{'dir'} = $main::OPTIONS{'format'}{$_}{'output_dir'}.'/';
            } else {
                $obj->{'final'}->{$_}->{'dir'} = $obj->{'original'}->{'dir'}.$main::OPTIONS{'format'}{$_}{'output_dir'}.'/';
            }
        } else {
            $obj->{'final'}->{$_}->{'dir'} = $obj->{'original'}->{'dir'}.$_.'/';
        }
    }

    $obj->{'final'}->{'extension'} = '.mp4';

    return 1;
}

sub get_name {
    my $obj = shift;

    lock $obj;

    if ($main::OPTIONS{'keep_name'} eq 'true') {
        $obj->{'final'}->{'name'} = $obj->{'original'}->{'name'};
    }
    else {
        my $info = ImageInfo($obj->{'original'}->{'path'}, 'CreateDate');

        if (not exists $info->{'CreateDate'} or $info->{'CreateDate'} eq '0000:00:00 00:00:00') {
            print STDERR "[$obj->{'original'}->{'path'}] Failed to get capture time, keeping original name...\n";
            $obj->{'final'}->{'name'} = $obj->{'original'}->{'name'};
        } else {
            my $t = Time::Piece->strptime($info->{'CreateDate'}, "%Y:%m:%d %H:%M:%S");
            if ($main::OPTIONS{'tzoffset'} != 0) {
                print "COUCOU: $main::OPTIONS{'tzoffset'}\n";
                $t += $main::OPTIONS{'tzoffset'};
            } else {
                $t += $t->localtime->tzoffset;
            }
            $obj->{'final'}->{'name'} = $t->ymd('').'-'.$t->hms('');

            print "[$obj->{'original'}->{'path'}] Renamed to \'$obj->{'final'}->{'name'}\'\n"
            if $main::OPTIONS{'verbose'} eq 'true';
        }
    }

    # set final path
    foreach (keys %{ $main::OPTIONS{'format'} }) {
        next if $main::OPTIONS{'format'}{$_}{'type'} ne 'video';
        $obj->{'final'}->{$_}->{'path'} = $obj->{'final'}->{$_}->{'dir'}
        .$obj->{'final'}->{'name'}
        .$obj->{'final'}->{'extension'};
    }

    return 1;
}

sub exist {
    my $obj = shift;

    lock $obj;

    foreach (keys %{ $main::OPTIONS{'format'} }) {
        next if $main::OPTIONS{'format'}{$_}{'type'} ne 'video';

        print "$obj->{'original'}->{'path'} -> $obj->{'final'}->{$_}->{'path'}\n"
        if $main::OPTIONS{'verbose'} eq 'false' and $main::OPTIONS{'batch'} ne 'true';

        if (-f $obj->{'final'}->{$_}->{'path'}) {
            print "[$obj->{'final'}->{$_}->{'path'}] Already exist...\n"
            if $main::OPTIONS{'overwrite'} eq 'false';

            $obj->{'final'}->{$_}->{'exist'} = 1;
        }
    }

    return 1;
}

sub create {
    my $obj = shift;

    lock $obj;

    foreach (keys %{ $main::OPTIONS{'format'} }) {
        next if $main::OPTIONS{'format'}{$_}{'type'} ne 'video';
        next if defined $obj->{'final'}->{$_}->{'exist'} and $main::OPTIONS{'overwrite'} eq 'false';

        print "[$obj->{'final'}->{$_}->{'path'}] Creating...\n" if $main::OPTIONS{'verbose'} eq 'true';

        make_path $obj->{'final'}->{$_}->{'dir'} if not -d $obj->{'final'}->{$_}->{'dir'};
        copy("$obj->{'original'}->{'path'}", "$obj->{'final'}->{$_}->{'path'}");
    }

    return 1;
}

sub process {
    my $obj = shift;

    lock $obj;

    foreach (keys %{ $main::OPTIONS{'format'} }) {
        next if $main::OPTIONS{'format'}{$_}{'type'} ne 'video';
        next if not defined $main::OPTIONS{'format'}{$_}{'reencode'} or $main::OPTIONS{'format'}{$_}{'reencode'} eq 'false';
        next if defined $obj->{'final'}->{$_}->{'exist'} and $main::OPTIONS{'overwrite'} eq 'false';

        print "[$obj->{'final'}->{$_}->{'path'}] Processing...\n" if $main::OPTIONS{'verbose'} eq 'true';

        my $tmp_file = File::Temp->new('process-media_tmp.XXXXXXXXXXXXX', DIR => $obj->{'final'}->{$_}->{'dir'});

        my $cmd = "$ffmpeg -nostdin -hide_banner -y";

        $cmd .= ($main::OPTIONS{'verbose'} eq 'true') ? " -loglevel warning" : " -loglevel error";

        if (not defined $main::OPTIONS{'format'}{$_}{'rotate'} or $main::OPTIONS{'format'}{$_}{'rotate'} =~ '^(?:90|180|270)$') {
            $cmd .= " -noautorotate";
        }

        $cmd .= " -i $obj->{'final'}->{$_}->{'path'}";

        # video codec
        if (defined $main::OPTIONS{'format'}{$_}{'vcodec'} and $main::OPTIONS{'format'}{$_}{'vcodec'} eq 'x265') {
            $cmd .= defined $main::OPTIONS{'format'}{$_}{'vcodec_params'} ? " -codec:v libx265 -x265-params $main::OPTIONS{'format'}{$_}{'vcodec_params'}:log-level=error" : " -codec:v libx265";
        } else {
            $cmd .= defined $main::OPTIONS{'format'}{$_}{'vcodec_params'} ? " -codec:v libx264 -x264-params $main::OPTIONS{'format'}{$_}{'vcodec_params'}" : " -codec:v libx264";
        }

        # get original audio codec
        chomp (my $caudio = `$ffprobe -show_streams -select_streams a $obj->{'original'}->{'path'} 2>&1 | grep codec_name | sed 's/^codec_name=//'`);
        if (not defined $caudio) {
            carp "[$obj->{'original'}->{'path'}] Failed to get audio codec";
            return 0;
        }

        # audio codec
        if ($caudio eq 'aac') {
            $cmd .= " -codec:a copy";
        } else {
            $cmd .= " -codec:a aac -b:a 160k";
        }

        # copy all metadata
        $cmd .= " -map_metadata 0";
        # if we force the copy of stream tags, orientation tag persist even after autorotate, which is problematic
#        $cmd .= " -map_metadata 0 -map_metadata:s:v 0:s:v -map_metadata:s:a 0:s:a";

        # filters
        if (defined $main::OPTIONS{'format'}{$_}{'resize'} or defined $main::OPTIONS{'format'}{$_}{'rotate'}) {

            my @vf;

            # rotate
            if (defined $main::OPTIONS{'format'}{$_}{'rotate'} and $main::OPTIONS{'format'}{$_}{'rotate'} =~ '^(?:90|180|270)$') {

                # if forced rotation, remove rotate metadata
                $cmd .= " -metadata:s:v rotate=0";

                push @vf, "transpose=1" if $main::OPTIONS{'format'}{$_}{'rotate'} == 90;
                push @vf, "transpose=1,transpose=1" if $main::OPTIONS{'format'}{$_}{'rotate'} == 180;
                push @vf, "transpose=1,transpose=1,transpose=1" if $main::OPTIONS{'format'}{$_}{'rotate'} == 270;
            }

            # resize
            push @vf, "scale=iw*min(1\\,min($main::OPTIONS{'format'}{$_}{'resize'}/iw\\,$main::OPTIONS{'format'}{$_}{'resize'}/ih)):-1"
            if defined $main::OPTIONS{'format'}{$_}{'resize'};

            if (@vf) {
                $cmd .= " -vf \"";
                $cmd .= join(',', @vf);
                $cmd .= "\"";
            }
        }

        $cmd .= " -flags +global_header";
        $cmd .= " -f mp4 $tmp_file";

#        print "$cmd\n" if $main::OPTIONS{'verbose'} eq 'true';

        &execute($obj->{'final'}->{$_}->{'path'}, 'Failed to encode', $cmd);

        move($tmp_file, $obj->{'final'}->{$_}->{'path'});
    }

    return 1;
}

sub strip {
    my $obj = shift;

    lock $obj;

    foreach (keys %{ $main::OPTIONS{'format'} }) {
        next if $main::OPTIONS{'format'}{$_}{'type'} ne 'video';
        next if not defined $main::OPTIONS{'format'}{$_}{'strip'} or $main::OPTIONS{'format'}{$_}{'strip'} eq 'false';
        next if defined $obj->{'final'}->{$_}->{'exist'} and $main::OPTIONS{'overwrite'} eq 'false';

        print "[$obj->{'final'}->{$_}->{'path'}] Stripping...\n" if $main::OPTIONS{'verbose'} eq 'true';

        my $tmp_data;

        # dump metadata
        if (defined $main::OPTIONS{'format'}{$_}{'strip_exclude'}) {
            $tmp_data = File::Temp->new('process-media_tmp.XXXXXXXXXXXXX', DIR => $obj->{'final'}->{$_}->{'dir'});
            my $cmd = "$ffmpeg -nostdin -hide_banner -y";
            $cmd .= ($main::OPTIONS{'verbose'} eq 'true') ? " -loglevel warning" : " -loglevel error";
            $cmd .= " -i $obj->{'final'}->{$_}->{'path'}";
            $cmd .= " -f ffmetadata $tmp_data";
            &execute($obj->{'final'}->{$_}->{'path'}, 'Failed to encode', $cmd);
            &edit_metadata($tmp_data);
        }

        my $tmp_video = File::Temp->new('process-media_tmp.XXXXXXXXXXXXX', DIR => $obj->{'final'}->{$_}->{'dir'});

        # strip all metadata
        my $cmd = "$ffmpeg -nostdin -hide_banner -y";
        $cmd .= ($main::OPTIONS{'verbose'} eq 'true') ? " -loglevel warning" : " -loglevel error";
        $cmd .= " -i $obj->{'final'}->{$_}->{'path'}";
        $cmd .= " -codec copy";
        $cmd .= " -map_metadata -1 -map_metadata:s:v -1 -map_metadata:s:a -1";
        $cmd .= " -f mp4 $tmp_video";
        &execute($obj->{'final'}->{$_}->{'path'}, 'Failed to encode', $cmd);
        move($tmp_video, $obj->{'final'}->{$_}->{'path'});

        # import wanted metadata
        if (defined $main::OPTIONS{'format'}{$_}{'strip_exclude'}) {
            my $tmp_video2 = File::Temp->new('process-media_tmp.XXXXXXXXXXXXX', DIR => $obj->{'final'}->{$_}->{'dir'});
            my $cmd2 = "$ffmpeg -nostdin -hide_banner -y";
            $cmd2 .= ($main::OPTIONS{'verbose'} eq 'true') ? " -loglevel warning" : " -loglevel error";
            $cmd2 .= " -i $obj->{'final'}->{$_}->{'path'}";
            $cmd2 .= " -i $tmp_data -map_metadata 1 -codec copy";
            $cmd2 .= " -f mp4 $tmp_video2";
            &execute($obj->{'final'}->{$_}->{'path'}, 'Failed to encode', $cmd2);
            move($tmp_video2, $obj->{'final'}->{$_}->{'path'});
        }
    }

    return 1;
}

sub thumbnail {
    my $obj = shift;

    lock $obj;

    foreach (keys %{ $main::OPTIONS{'format'} }) {
        next if $main::OPTIONS{'format'}{$_}{'type'} ne 'video';
        next if not defined $main::OPTIONS{'format'}{$_}{'thumbnail'} or $main::OPTIONS{'format'}{$_}{'thumbnail'} eq 'false';
        next if defined $obj->{'final'}->{$_}->{'exist'} and $main::OPTIONS{'overwrite'} eq 'false';

        print "[$obj->{'final'}->{$_}->{'path'}] Generating thumbnail...\n" if $main::OPTIONS{'verbose'} eq 'true';

        &execute($obj->{'final'}->{$_}->{'path'}, 'Failed to create thumbnail', "$ffmpeg -y -loglevel error -i $obj->{'final'}->{$_}->{'path'} -vframes 1 $obj->{'final'}->{$_}->{'dir'}$obj->{'final'}->{'name'}.jpg");

        my $image = Image::Magick->new();
        if (my $err = $image->Read("$obj->{'final'}->{$_}->{'dir'}$obj->{'final'}->{'name'}.jpg")){
            carp "[$obj->{'final'}->{$_}->{'dir'}$obj->{'final'}->{'name'}.jpg] Failed to read, $err";
            return 0;
        }
        if (my $err = $image->Strip()){
            carp "[$obj->{'final'}->{$_}->{'dir'}$obj->{'final'}->{'name'}.jpg] Failed to strip, $err";
            return 0;
        }
        if (my $err = $image->Write(filename => "$obj->{'final'}->{$_}->{'dir'}$obj->{'final'}->{'name'}.jpg", interlace => 'Plane', quality => 90)) {
            carp "[$obj->{'final'}->{$_}->{'dir'}$obj->{'final'}->{'name'}.jpg] Failed to write, $err";
            return 0;
        }
    }

    return 1;
}

sub integrity {
    my $obj = shift;

    lock $obj;

    foreach (keys %{ $main::OPTIONS{'format'} }) {
        next if $main::OPTIONS{'format'}{$_}{'type'} ne 'video';
        next if defined $obj->{'final'}->{$_}->{'exist'} and $main::OPTIONS{'overwrite'} eq 'false';

        print "[$obj->{'final'}->{$_}->{'path'}] Checking integrity...\n" if $main::OPTIONS{'verbose'} eq 'true';

        &execute($obj->{'final'}->{$_}->{'path'}, 'File is corrupted', "$ffmpeg -loglevel error -i $obj->{'final'}->{$_}->{'path'} -f null -");
    }

    return 1;
}

sub search_duplicate {
    my ($class, @files) = @_;

    foreach my $i (0 .. $#files) {
        next if ref($files[$i]) ne 'Llavaud::Process::Media::Video';
        my %same;
        foreach my $j (0 .. $#files) {
            next if ref($files[$j]) ne 'Llavaud::Process::Media::Video';
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
            carp "[$file] $msg, $!";
            return 0;
        }
    }

    # ffmpeg messes up terminal, this is a workaround
    system('stty sane');

    return 1;
}

sub edit_metadata {
    my $file = shift;

    my $fr = IO::File->new($file, q{<});
    my @ori = <$fr>;
    close $fr;

    my $fw = IO::File->new($file, q{>});
    foreach my $l (@ori) {
        my $keep = 0;
        if ($l =~ /^;FFMETADATA\d+$/) {
            print $fw $l;
            next;
        }
        foreach (split(',', $main::OPTIONS{'format'}{$_}{'strip_exclude'})) {
            if ($_ eq 'gps') {
                $keep = 1 if $l =~ /^location/;
            }
            elsif ($_ eq 'orientation') {
                $keep = 1 if $l =~ /^rotate/;
            }
        }
        print $fw $l if $keep;
    }
    close $fw;

    return 1;
}

1;
