# process-media

This script will process (resize, compress...) photos and videos according to the specified options.

## Installation

This script depends on several binary or Perl library, you need to install the following Debian/Ubuntu packages:

```bash
sudo apt-get install ffmpeg jpeginfo libimage-exiftool-perl libimage-magick-perl libmime-types-perl libsys-cpu-perl libterm-readkey-perl
```

Once the packages are installed, you just need to extract the zip/tar.gz archive and execute the **./process-media** binary

## CLI

```
Usage: ./process-media [options...] <path>
Options:
-t,--type        {photo,video}	Type of files to process (default: photo,video)
-f,--format      {format1,...}	Format to generate (default: all format defined in config file)
-m,--max_threads <num_threads>	Maximum allowed threads (default: number of cpu(s)/core(s))
-k,--keep_name                  Do not rename file
-v,--verbose                    Verbose output
-o,--overwrite                  Overwrite existing files
-b,--batch                      Run in non-interactive mode, allowing to run in a crontab
-h,--help                       This help text
```

## Configuration

