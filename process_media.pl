#!/usr/bin/perl

use strict;
use warnings;

# need perl 5.14 to allow syntax: package A { ... }
require 5.014;

use Data::Dumper;
use Getopt::Long qw/GetOptions/;
use Sys::CPU qw/cpu_count/;
use Term::ReadKey qw/ReadKey ReadMode/;
use threads;
use threads::shared;
use Thread::Queue;
use Time::HiRes qw/sleep/;
use YAML::Tiny;

# Own modules
use lib './libs';
use Photo;
use Video;

$SIG{'INT'}  = \&sig_handler;
$SIG{'TERM'} = \&sig_handler;

## VARS

my $config_file = 'process_media.yaml';
my $path;
my @threads;
my @objects;
my $opts = &share({}); # shared variables must be declared before populating it
my %options;

## MAIN

my $conf = YAML::Tiny->read($config_file);

&check_conf();

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

&set_options();

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

sub set_options {

    # default values
    # need perl >=5.10 for operator //

    # max_threads
    if (defined $opts->{'max_threads'}) {
        $options{'max_threads'} = ($opts->{'max_threads'} == 0) ? Sys::CPU::cpu_count() : $opts->{'max_threads'};
    } else {
        $options{'max_threads'} = ($conf->[0]->{'options'}->{'max_threads'} == 0) ? Sys::CPU::cpu_count() : $conf->[0]->{'options'}->{'max_threads'};
    }

    # codec
    $options{'codec'} = $opts->{'codec'} // $conf->[0]->{'options'}->{'codec'};

    # verbose
    $options{'verbose'} = $opts->{'verbose'} // $conf->[0]->{'options'}->{'verbose'};

    # overwrite
    $options{'overwrite'} = $opts->{'overwrite'} // $conf->[0]->{'options'}->{'overwrite'};

    # keep_name
    $options{'keep_name'} = $opts->{'keep_name'} // $conf->[0]->{'options'}->{'keep_name'};

    # gps
    $options{'gps'} = $opts->{'gps'} // $conf->[0]->{'options'}->{'gps'};

    $options{'regex_photo'} = $conf->[0]->{'options'}->{'regex_photo'};
    $options{'regex_video'} = $conf->[0]->{'options'}->{'regex_video'};

    # format
    if ($opts->{'format'}) {
        $options{'format'} = $opts->{'format'};
    } else {
        my %f;
        foreach my $h (@{ $conf->[0]->{'format'} }) {
            $f{$h->{'name'}} = 1;
        }
        $options{'format'} = join(',', keys %f);
    }

    # type
    $options{'type'} = $opts->{'type'} // 'photo,video';

    $path = $ARGV[0] // './';

    return 1;
}

sub check_conf {

    # section
    foreach (keys %{ $conf->[0] }) {
        die "Unknown section \'$_\' in config file" if $_ !~ /^(options|format)$/;
    }

    # options
    foreach (keys %{ $conf->[0]->{'options'} }) {
        die "Unknown option \'$_\' in config file" if $_ !~ /^(max_threads|codec|gps|verbose|keep_name|overwrite|regex_photo|regex_video)$/;
    }

    # max_threads
    die "Miss/Bad value for 'max_threads' in config file\n"
        if not defined $conf->[0]->{'options'}->{'max_threads'} or $conf->[0]->{'options'}->{'max_threads'} !~ /^\d+$/;

    # codec
    die "Miss/Bad value for 'codec' in config file\n"
        if not defined $conf->[0]->{'options'}->{'codec'} or $conf->[0]->{'options'}->{'codec'} !~ /^(x26[45])$/;

    # gps
    die "Miss/Bad value for 'gps' in config file\n"
        if not defined $conf->[0]->{'options'}->{'gps'} or $conf->[0]->{'options'}->{'gps'} !~ /^(true|false)$/;

    # verbose
    die "Miss/Bad value for 'verbose' in config file\n"
        if not defined $conf->[0]->{'options'}->{'verbose'} or $conf->[0]->{'options'}->{'verbose'} !~ /^(true|false)$/;

    # keep_name
    die "Miss/Bad value for 'keep_name' in config file\n"
        if not defined $conf->[0]->{'options'}->{'keep_name'} or $conf->[0]->{'options'}->{'keep_name'} !~ /^(true|false)$/;

    # overwrite
    die "Miss/Bad value for 'overwrite' in config file\n"
        if not defined $conf->[0]->{'options'}->{'overwrite'} or $conf->[0]->{'options'}->{'overwrite'} !~ /^(true|false)$/;

    # regex_photo
    die "Miss/Bad value for 'regex_photo' in config file\n"
        if not defined $conf->[0]->{'options'}->{'regex_photo'};

    # regex_video
    die "Miss/Bad value for 'regex_video' in config file\n"
        if not defined $conf->[0]->{'options'}->{'regex_video'};

    # format
    foreach my $h (@{ $conf->[0]->{'format'} }) {
        foreach (keys %$h) {
            die "Unknown option \'$_\' in config file" if $_ !~ /^(name|type|rotate|reencode|resize|compress|strip)$/;

            # name
            die "Bad format name in config file\n" if $_ eq 'name' and $h->{'name'} !~ /^\w+$/;

            # type
            die "Bad format type in config file\n" if $_ eq 'type' and $h->{'type'} !~ /^(photo|video)$/;

            # rotate
            die "Bad format rotate in config file\n" if $_ eq 'rotate' and $h->{'rotate'} !~ /^(true|false)$/;

            # reencode
            die "Bad format reencode in config file\n" if $_ eq 'reencode' and $h->{'reencode'} !~ /^(true|false)$/;

            # resize
            die "Bad format resize in config file\n" if $_ eq 'resize' and $h->{'resize'} !~ /^[\dx><]+$/;

            # strip
            die "Bad format strip in config file\n" if $_ eq 'strip' and $h->{'strip'} !~ /^(true|false)$/;

            # compress
            die "Bad format compress in config file\n" if $_ eq 'compress' and $h->{'compress'} !~ /^\d+$/ and $h->{'compress'} > 100;
        }
    }

    return 1;
}

sub check_params {

    &usage() if $opts->{'help'};

    # type
    if (defined $opts->{'type'}) {
        foreach (split(',',$opts->{'type'})) {
            die "Bad type of files to process: $_, see help (-h) for supported type\n" unless /^(photo|video)$/;
        }
    }

    # format
    if (defined $opts->{'format'}) {
        foreach (split(',',$opts->{'format'})) {
            die "Bad format to generate: $_, see help (-h) for supported format\n" unless /^(archive|web)$/;
        }
    }

    # codec
    die "Bad video codec: $opts->{'codec'}, see help (-h) for supported codec\n"
        if defined $opts->{'codec'} and $opts->{'codec'} !~ /^x26[45]$/;

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
        if (/$conf->[0]->{'options'}->{'regex_photo'}/i) {
            next if $opts->{'type'} !~ /photos/;
            $obj = new Photo;
        }
        elsif (/$conf->[0]->{'options'}->{'regex_photo'}/i) {
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

## POD

=pod

=head1 NAME

process_media.pl

=head1 DESCRIPTION

This script will process (resize, compress...) photos and videos according to the specified options.

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
