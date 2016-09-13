# process-media

This script will process (resize, compress...) photos and videos according to the specified options.

For now it only support **JPEG** photo and **MP4** video.

## Installation

### Package (favourite)

I have setup a Debian/Ubuntu apt repository to distribute this package

You can add my personal repository to your **`/etc/apt/sources.list`** by adding the following line:

`deb https://llavaud.github.io/process-media/apt xenial universe`

You must also retrieve and install my GPG key:

`wget -O - https://llavaud.github.io/process-media/apt/conf/gpg.key | sudo apt-key add -`

And then install the package:

```
sudo apt-get update
sudo apt-get install process-media
```

### Archive

If you dont want to add a new repository on your system you can also retrieve the [latest zip/tar.gz archive](https://github.com/llavaud/process-media/releases/latest)

This script depends on several binary or Perl library, so you need to install the following **Debian/Ubuntu** packages before using it:

```bash
sudo apt-get install ffmpeg jpeginfo libimage-exiftool-perl libimage-magick-perl libmime-types-perl libsys-cpu-perl libterm-readkey-perl
```

Once the packages are installed, you just need to extract the archive

## Configuration

First you need to define the different formats you want in the configuration file, the script will search for a configuration file by respecting the following order:

**`/etc/process-media.yaml`**

**`process-media.yaml`**

Here is a photo format example:

```
web_photo:
  type: 'photo'
  rotate: true
  resize: '1920'
  compress: 90
  strip:
    - 'gps'
  output_dir: 'web'
```

Here we define a photo format named **web_photo**.

The resulting photo will be auto-rotated, resized, compressed and all metadata will be removed except GPS informations.

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
