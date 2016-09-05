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

# Own modules
use lib './libs';
use Photo;
use Video;

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
