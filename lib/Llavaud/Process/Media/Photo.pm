package Llavaud::Process::Media::Photo;

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
		next if $main::OPTIONS{'format'}{$_}{'type'} ne 'photo';
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

	$obj->{'final'}->{'extension'} = '.jpg';

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
		$obj->{'final'}->{'name'} = $t->ymd('').'-'.$t->hms('');

		print "[$obj->{'original'}->{'path'}] Renamed to \'$obj->{'final'}->{'name'}\'\n"
		if $main::OPTIONS{'verbose'} eq 'true';
	}

	# set final path
	foreach (keys %{ $main::OPTIONS{'format'} }) {
		next if $main::OPTIONS{'format'}{$_}{'type'} ne 'photo';
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
		next if $main::OPTIONS{'format'}{$_}{'type'} ne 'photo';

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
		next if $main::OPTIONS{'format'}{$_}{'type'} ne 'photo';
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
		next if $main::OPTIONS{'format'}{$_}{'type'} ne 'photo';
		next if defined $obj->{'final'}->{$_}->{'exist'} and $main::OPTIONS{'overwrite'} eq 'false';

		print "[$obj->{'final'}->{$_}->{'path'}] Processing...\n" if $main::OPTIONS{'verbose'} eq 'true';

		my $image = Image::Magick->new();
		if (my $err = $image->Read($obj->{'original'}->{'path'})){
			carp "[$obj->{'final'}->{$_}->{'path'}] Failed to read, $err";
			return 0;
		}
        if (defined $main::OPTIONS{'format'}{$_}{'rotate'}) {
            my $err;
            if ($main::OPTIONS{'format'}{$_}{'rotate'} eq 'auto') {
                $err = $image->AutoOrient();
            } else {
                $err = $image->Rotate($main::OPTIONS{'format'}{$_}{'rotate'});
                $err = $image->Set(orientation => 'top-left');
            }
            if ($err) {
                carp "[$obj->{'final'}->{$_}->{'path'}] Failed to auto-orient, $err";
                return 0;
            }
        }
		# resize image to get the larger side to 1920 (only if it is larger than 1920) and preserve aspect ratio
		if (defined $main::OPTIONS{'format'}{$_}{'resize'} and
			my $err = $image->Resize("$main::OPTIONS{'format'}{$_}{'resize'}x$main::OPTIONS{'format'}{$_}{'resize'}>")){
			carp "[$obj->{'final'}->{$_}->{'path'}] Failed to resize, $err";
			return 0;
		}
		my $err;
		if (defined $main::OPTIONS{'format'}{$_}{'compress'}) {
			$err = $image->Write(filename => $obj->{'final'}->{$_}->{'path'}, quality => $main::OPTIONS{'format'}{$_}{'compress'});
		} else {
			$err = $image->Write(filename => $obj->{'final'}->{$_}->{'path'});
		}
		if ($err) {
			carp "[$obj->{'final'}->{$_}->{'path'}] Failed to write, $err";
			return 0;
		}
	}

	return 1;
}

sub strip {
	my $obj = shift;

	lock $obj;

	foreach my $fname (keys %{ $main::OPTIONS{'format'} }) {
		next if $main::OPTIONS{'format'}{$fname}{'type'} ne 'photo';
		next if not defined $main::OPTIONS{'format'}{$fname}{'strip'} or
		$main::OPTIONS{'format'}{$fname}{'strip'} eq 'false';
		next if defined $obj->{'final'}->{$fname}->{'exist'} and $main::OPTIONS{'overwrite'} eq 'false';

		print "[$obj->{'final'}->{$fname}->{'path'}] Stripping...\n" if $main::OPTIONS{'verbose'} eq 'true';

		# remove all tags
		my $exif = Image::ExifTool->new();
		my ($ret, $err) = $exif->SetNewValue('*');
		if (defined $err) {
			carp "[$obj->{'final'}->{$fname}->{'path'}] Failed to remove tags, $err";
			return 0;
		}

		if (defined $main::OPTIONS{'format'}{$fname}{'strip_exclude'}) {

			foreach (split(',', $main::OPTIONS{'format'}{$fname}{'strip_exclude'})) {

				if ($_ eq 'gps') {

					# keep GPS tags if asked
					$ret = $exif->SetNewValuesFromFile($obj->{'final'}->{$fname}->{'path'}, 'gps:all');
					if (defined $ret->{'Error'}) {
						carp "[$obj->{'final'}->{$fname}->{'path'}] Failed to retrieve tag orientation, $ret->{'Error'}";
						return 0;
					}
				}
				elsif ($_ eq 'orientation') {

					# keep Orientation tag
					$ret = $exif->SetNewValuesFromFile($obj->{'final'}->{$fname}->{'path'}, 'EXIF:Orientation');
					if (defined $ret->{'Error'}) {
						carp "[$obj->{'final'}->{$fname}->{'path'}] Failed to retrieve tag orientation, $ret->{'Error'}";
						return 0;
					}
				}
			}
		}

		unless ($exif->WriteInfo($obj->{'final'}->{$fname}->{'path'})) {
			carp "[$obj->{'final'}->{$fname}->{'path'}] Failed to write, ".$exif->GetValue('Error');
			return 0;
		}
	}

	return 1;
}

sub integrity {
	my $obj = shift;

	lock $obj;

	foreach (keys %{ $main::OPTIONS{'format'} }) {
		next if $main::OPTIONS{'format'}{$_}{'type'} ne 'photo';
		next if defined $obj->{'final'}->{$_}->{'exist'} and $main::OPTIONS{'overwrite'} eq 'false';

		print "[$obj->{'final'}->{$_}->{'path'}] Checking integrity...\n" if $main::OPTIONS{'verbose'} eq 'true';

		&execute($obj->{'final'}->{$_}->{'path'}, 'File is corrupted', "jpeginfo -c $obj->{'final'}->{$_}->{'path'} >/dev/null 2>&1");
	}

	return 1;
}

sub search_duplicate {
	my ($class, @files) = @_;

	foreach my $i (0 .. $#files) {
		next if ref($files[$i]) ne 'Llavaud::Process::Media::Photo';
		my %same;
		foreach my $j (0 .. $#files) {
			next if ref($files[$j]) ne 'Llavaud::Process::Media::Photo';
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

	return 1;
}

1;
