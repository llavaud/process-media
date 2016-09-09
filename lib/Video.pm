package Video;

use strict;
use warnings;

use Carp qw/carp/;
use File::Basename qw/fileparse/;
use File::Copy qw/copy/;
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

    $obj->{'final'}->{'extension'} = lc $obj->{'original'}->{'extension'};

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

        if (not exists $info->{'CreateDate'}) {
            carp "[$obj->{'original'}->{'path'}] Failed to get capture time";
            return 0;
        }

        my $t = Time::Piece->strptime($info->{'CreateDate'}, "%Y:%m:%d %H:%M:%S");
        $t += $t->localtime->tzoffset;
        $obj->{'final'}->{'name'} = $t->ymd('').'-'.$t->hms('');
    }

    print "[$obj->{'original'}->{'path'}] Rename to \'$obj->{'final'}->{'name'}\'\n"
        if $main::OPTIONS{'verbose'} eq 'true';

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

    print "$obj->{'original'}->{'path'} -> $obj->{'final'}->{'name'}\n"
        if $main::OPTIONS{'verbose'} eq 'false' and $main::OPTIONS{'batch'} ne 'true';

    foreach (keys %{ $main::OPTIONS{'format'} }) {
        next if $main::OPTIONS{'format'}{$_}{'type'} ne 'video';

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

        make_path $obj->{'final'}->{$_}->{'dir'} unless -d $obj->{'final'}->{$_}->{'dir'};
        copy("$obj->{'original'}->{'path'}", "$obj->{'final'}->{$_}->{'path'}");
    }

    return 1;
}

sub process {
    my $obj = shift;

    lock $obj;

    foreach (keys %{ $main::OPTIONS{'format'} }) {
        next if $main::OPTIONS{'format'}{$_}{'type'} ne 'video';
        next if defined $main::OPTIONS{'format'}{$_}{'reencode'} and $main::OPTIONS{'format'}{$_}{'reencode'} eq 'false';
        next if defined $obj->{'final'}->{$_}->{'exist'} and $main::OPTIONS{'overwrite'} eq 'false';

        print "[$obj->{'final'}->{$_}->{'path'}] Processing...\n" if $main::OPTIONS{'verbose'} eq 'true';

		my $cmd = "ffmpeg -nostdin -hide_banner -y -loglevel warning -i $obj->{'original'}->{'path'} -codec:a copy -flags +global_header";

		if (defined $main::OPTIONS{'format'}{$_}{'codec'} and $main::OPTIONS{'format'}{$_}{'codec'} eq 'x265') {
			$cmd .= " -codec:v libx265 -x265-params crf=23:log-level=error";
		}

		if (defined $main::OPTIONS{'format'}{$_}{'resize'}) {
            $cmd .= " -vf \"scale='if(gt(iw,ih),$main::OPTIONS{'format'}{$_}{'resize'},trunc(oh*a/2)*2)':'if(gt(iw,ih),trunc(ow/a/2)*2,$main::OPTIONS{'format'}{$_}{'resize'})'\"";
        }

        $cmd .= " $obj->{'final'}->{$_}->{'path'}";

        &execute($obj->{'final'}->{$_}->{'path'}, 'Failed to encode', $cmd);
    }

    return 1;
}

sub strip {
    my $obj = shift;

    lock $obj;

    foreach (keys %{ $main::OPTIONS{'format'} }) {
        next if $main::OPTIONS{'format'}{$_}{'type'} ne 'video';
        next if not defined $main::OPTIONS{'format'}{$_}{'strip'};
        next if defined $obj->{'final'}->{$_}->{'exist'} and $main::OPTIONS{'overwrite'} eq 'false';

        print "[$obj->{'final'}->{$_}->{'path'}] Stripping...\n" if $main::OPTIONS{'verbose'} eq 'true';

        # remove all tags
        my $exif = Image::ExifTool->new();
        my ($ret, $err) = $exif->SetNewValue('*');
        if (defined $err) {
            carp "[$obj->{'final'}->{$_}->{'path'}] Failed to remove tags, $err";
            return 0;
        }
        unless ($exif->WriteInfo($obj->{'final'}->{$_}->{'path'})) {
            carp "[$obj->{'final'}->{$_}->{'path'}] Failed to write, ".$exif->GetValue('Error');
            return 0;
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

        &execute($obj->{'final'}->{$_}->{'path'}, 'Failed to create thumbnail', "ffmpeg -y -loglevel error -i $obj->{'final'}->{$_}->{'path'} -vframes 1 $obj->{'final'}->{$_}->{'dir'}$obj->{'final'}->{'name'}.jpg");

        my $image = Image::Magick->new();
        if (my $err = $image->Read("$obj->{'final'}->{$_}->{'dir'}$obj->{'final'}->{'name'}.jpg")){
            carp "[$obj->{'final'}->{$_}->{'dir'}$obj->{'final'}->{'name'}.jpg] Failed to read, $err";
            return 0;
        }
        if (my $err = $image->Strip()){
            carp "[$obj->{'final'}->{$_}->{'dir'}$obj->{'final'}->{'name'}.jpg] Failed to strip, $err";
            return 0;
        }
        if (my $err = $image->Write(filename => "$obj->{'final'}->{$_}->{'dir'}$obj->{'final'}->{'name'}.jpg", quality => 90)) {
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

        &execute($obj->{'final'}->{$_}->{'path'}, 'File is corrupted', "ffmpeg -loglevel error -i $obj->{'final'}->{$_}->{'path'} -f null -");
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
            carp "[$file] $msg, $!";
            return 0;
        }
    }

    # ffmpeg messes up terminal, this is a workaround
    system('stty sane');

    return 1;
}

1;
