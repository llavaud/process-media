package Photo;

use strict;
use warnings;

use Data::Dumper;
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
    foreach (keys %{ $main::options{'format'} }) {
        next if $main::options{'format'}{$_}{'type'} ne 'photo';
        $obj->{'final'}->{$_} = &share({});
        if (defined $main::options{'format'}{$_}{'output_dir'}) {
            $obj->{'final'}->{$_}->{'dir'} = $obj->{'original'}->{'dir'}.$main::options{'format'}{$_}{'output_dir'}.'/';
        } else {
            $obj->{'final'}->{$_}->{'dir'} = $obj->{'original'}->{'dir'}.$_.'/';
        }
    }

	$obj->{'final'}->{'extension'} = $obj->{'original'}->{'extension'};

	return 1;
}

sub rename {
	my $obj = shift;

	lock $obj;

	if ($main::options{'keep_name'} eq 'true') {
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

	print "[$obj->{'original'}->{'path'}] Rename to \'$obj->{'final'}->{'name'}\'\n"
        if $main::options{'verbose'} eq 'true';

	# set final path
	foreach (keys %{ $main::options{'format'} }) {
        next if $main::options{'format'}{$_}{'type'} ne 'photo';
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
        if not defined $main::options{'verbose'};

	foreach (keys %{ $main::options{'format'} }) {
        next if $main::options{'format'}{$_}{'type'} ne 'photo';

		if (-f $obj->{'final'}->{$_}->{'path'}) {
			print "[$obj->{'final'}->{$_}->{'path'}] Already exist...\n"
                if $main::options{'overwrite'} eq 'false';

			$obj->{'final'}->{$_}->{'exist'} = 1;
		}
	}

	return 1;
}

sub create {
	my $obj = shift;

	lock $obj;

	foreach (keys %{ $main::options{'format'} }) {
        next if $main::options{'format'}{$_}{'type'} ne 'photo';
		next if defined $obj->{'final'}->{$_}->{'exist'} and $main::options{'overwrite'} eq 'false';

		print "[$obj->{'final'}->{$_}->{'path'}] Creating...\n" if $main::options{'verbose'} eq 'true';

		make_path $obj->{'final'}->{$_}->{'dir'} unless -d $obj->{'final'}->{$_}->{'dir'};
        copy("$obj->{'original'}->{'path'}", "$obj->{'final'}->{$_}->{'path'}");
    }

    return 1;
}

sub rotate {
	my $obj = shift;

	lock $obj;

	foreach (keys %{ $main::options{'format'} }) {
        next if $main::options{'format'}{$_}{'type'} ne 'photo';
        next if not defined $main::options{'format'}{$_}{'rotate'} or $main::options{'format'}{$_}{'rotate'} ne 'true';
		next if defined $obj->{'final'}->{$_}->{'exist'} and $main::options{'overwrite'} eq 'false';

		print "[$obj->{'final'}->{$_}->{'path'}] Rotating...\n" if $main::options{'verbose'} eq 'true';

		my $image = new Image::Magick;
		if (my $err = $image->Read($obj->{'original'}->{'path'})){
			warn "[$obj->{'final'}->{$_}->{'path'}] Failed to read, $err";
			return 0;
		}
		# physically rotate image according to the exif orientation tag
		if (my $err = $image->AutoOrient()) {
			warn "[$obj->{'final'}->{$_}->{'path'}] Failed to auto-orient, $err";
			return 0;
		}
		if (my $err = $image->Write($obj->{'final'}->{$_}->{'path'})) {
			warn "[$obj->{'final'}->{$_}->{'path'}] Failed to write, $err";
			return 0;
		}
	}

	return 1;
}

sub resize {
	my $obj = shift;

	lock $obj;

	foreach (keys %{ $main::options{'format'} }) {
        next if $main::options{'format'}{$_}{'type'} ne 'photo';
        next if not defined $main::options{'format'}{$_}{'resize'};
		next if defined $obj->{'final'}->{$_}->{'exist'} and $main::options{'overwrite'} eq 'false';

		print "[$obj->{'final'}->{$_}->{'path'}] Resizing...\n" if $main::options{'verbose'} eq 'true';

		my $image = new Image::Magick;
		if (my $err = $image->Read($obj->{'final'}->{$_}->{'path'})){
			warn "[$obj->{'final'}->{$_}->{'path'}] Failed to read, $err";
			return 0;
		}
		# resize image to get the larger side to 1920 (only if it is larger than 1920) and preserve aspect ratio
		if (my $err = $image->Resize($main::options{'format'}{$_}{'resize'})){
			warn "[$obj->{'final'}->{$_}->{'path'}] Failed to resize, $err";
			return 0;
		}
		if (my $err = $image->Write($obj->{'final'}->{$_}->{'path'})) {
			warn "[$obj->{'final'}->{$_}->{'path'}] Failed to write, $err";
			return 0;
		}
    }

    return 1;
}

sub compress {
	my $obj = shift;

	lock $obj;

	foreach (keys %{ $main::options{'format'} }) {
        next if $main::options{'format'}{$_}{'type'} ne 'photo';
        next if not defined $main::options{'format'}{$_}{'compress'};
		next if defined $obj->{'final'}->{$_}->{'exist'} and $main::options{'overwrite'} eq 'false';

		print "[$obj->{'final'}->{$_}->{'path'}] Compressing...\n" if $main::options{'verbose'} eq 'true';

		my $image = new Image::Magick;
		if (my $err = $image->Read($obj->{'final'}->{$_}->{'path'})){
			warn "[$obj->{'final'}->{$_}->{'path'}] Failed to read, $err";
			return 0;
		}
		if (my $err = $image->Write(filename => $obj->{'final'}->{$_}->{'path'}, quality => $main::options{'format'}{$_}{'compress'})) {
			warn "[$obj->{'final'}->{$_}->{'path'}] Failed to write, $err";
			return 0;
		}
    }

    return 1;
}

sub strip {
	my $obj = shift;

	lock $obj;

	foreach my $fname (keys %{ $main::options{'format'} }) {
        next if $main::options{'format'}{$fname}{'type'} ne 'photo';
        next if not defined $main::options{'format'}{$fname}{'strip'};
		next if defined $obj->{'final'}->{$fname}->{'exist'} and $main::options{'overwrite'} eq 'false';

		print "[$obj->{'final'}->{$fname}->{'path'}] Stripping...\n" if $main::options{'verbose'} eq 'true';

		# remove all tags
		my $exif = new Image::ExifTool;
		my ($ret, $err);
        ($ret, $err) = $exif->SetNewValue('*');
        if (defined $err) {
            warn "[$obj->{'final'}->{$fname}->{'path'}] Failed to remove tags, $err";
            return 0;
        }

        if (ref $main::options{'format'}{$fname}{'strip'} eq 'ARRAY') {

            foreach (@{ $main::options{'format'}{$fname}{'strip'} }) {

                if ($_ eq 'gps') {

                    # keep GPS tags if asked
                    $ret = $exif->SetNewValuesFromFile($obj->{'final'}->{$fname}->{'path'}, 'gps:all');
                    if (defined $ret->{'Error'}) {
                        warn "[$obj->{'final'}->{$fname}->{'path'}] Failed to retrieve tag orientation, $ret->{'Error'}";
                        return 0;
                    }
                }
                elsif ($_ eq 'orientation') {
                    # keep Orientation tag
                    $ret = $exif->SetNewValuesFromFile($obj->{'final'}->{$fname}->{'path'}, 'EXIF:Orientation');
                    if (defined $ret->{'Error'}) {
                        warn "[$obj->{'final'}->{$fname}->{'path'}] Failed to retrieve tag orientation, $ret->{'Error'}";
                        return 0;
                    }
                }
            }
        }

        unless ($exif->WriteInfo($obj->{'final'}->{$fname}->{'path'})) {
            warn "[$obj->{'final'}->{$fname}->{'path'}] Failed to write, ".$exif->GetValue('Error');
            return 0;
        }
    }

    return 1;
}

sub integrity {
	my $obj = shift;

	lock $obj;

    foreach (keys %{ $main::options{'format'} }) {
        next if $main::options{'format'}{$_}{'type'} ne 'photo';
        next if defined $obj->{'final'}->{$_}->{'exist'} and $main::options{'overwrite'} eq 'false';

		print "[$obj->{'final'}->{$_}->{'path'}] Checking integrity...\n" if $main::options{'verbose'} eq 'true';

		&execute($obj->{'final'}->{$_}->{'path'}, 'File is corrupted', "jpeginfo -c $obj->{'final'}->{$_}->{'path'} >/dev/null 2>&1");
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
