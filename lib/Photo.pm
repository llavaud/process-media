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
	foreach (split(',',$obj->{'options'}->{'format'})) {
        $obj->{'final'}->{$_} = &share({});
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

sub create {
	my $obj = shift;

	lock $obj;

	foreach (split(',',$obj->{'options'}->{'format'})) {
		print "[$obj->{'final'}->{$_}->{'path'}] Creating...\n" if defined $obj->{'options'}->{'verbose'};
		make_path $obj->{'final'}->{$_}->{'dir'} unless -d $obj->{'final'}->{$_}->{'dir'};
        copy("$obj->{'original'}->{'path'}", "$obj->{'final'}->{$_}->{'path'}");
    }

    return 1;
}

sub rotate {
	my $obj = shift;

	lock $obj;

	foreach my $f (split(',',$obj->{'options'}->{'format'})) {

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

1;
