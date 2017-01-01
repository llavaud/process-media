# process-media

This script will process (resize, compress...) photos and videos according to the specified options.

## Table of contents
* [Installation](#installation)
  * [Package (favourite)](#package)
  * [Archive](#archive)
* [Configuration](#configuration)
* [CLI](#cli)
  * [Examples](#examples)

## Installation

<a name="package"/>
### Package (favourite)

I have setup a **Debian/Ubuntu** apt repository to distribute this package

You can add my personal repository to your **`/etc/apt/sources.list`** by adding the following line:

`deb https://llavaud.github.io/process-media/apt stable main`

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
sudo apt-get install jpeginfo libimage-exiftool-perl libimage-magick-perl libmime-types-perl libsys-cpu-perl libterm-readkey-perl libyaml-tiny-perl
```

Once the packages are installed, you just need to extract the archive

## Configuration

First you need to define the different formats you want in the configuration file, the script will search for a configuration file by respecting the following order:

1. **`process-media.yaml`**
2. **`/etc/process-media.yaml`**

Here is a photo format example:

```
web_photo:
  type: 'photo'
  rotate: 'auto'
  resize: 1920
  compress: 90
  progressive: true
  strip: true
  strip_exclude: 'gps'
  output_dir: 'web'
```

Here we define a photo format named **web_photo**.

The resulting photo(s) will be auto-rotated, resized, compressed, progressive jpeg enabled and all metadata will be removed except GPS informations.

## CLI

```
Usage: ./process-media <path> [options]

<path> is the path to photos or videos to process

Options:
-t,--type        {photo,video}  Type of files to process (default: photo,video)
-f,--format      {format1,...}  Format to generate (default: all format defined in config file)
-c,--config      <config_file>  Config file to load (default: search local process-media.yaml file or in /etc)
-m,--max_threads <num_threads>  Maximum allowed threads (default: number of cpu(s)/core(s))
-k,--keep_name                  Do not rename file
-v,--verbose                    Verbose output
-o,--overwrite                  Overwrite existing files
-b,--batch                      Run in non-interactive mode, allowing to run in a crontab
-h,--help                       This help text
```

### Examples

* If you want to convert all photos and videos in the current directory by using all defined format(s) from the configuration file:

`process-media`

* If you want to convert all photos in the folder **/home/foo** by using the previous define format **web_photo**:

`process-media /home/foo -f web_photo`
