package Video;

use strict;
use warnings;

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
    foreach (keys %{ $main::options{'format'} }) {
        next if $main::options{'format'}{$_}{'type'} ne 'video';
        $obj->{'final'}->{$_} = &share({});
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

1;
