## 1.5 (2017-09-12)

IMPROVEMENTS:

BUG FIXES:
* correcting a bug with threads management

## 1.4 (2017-09-05)

IMPROVEMENTS:
* improved signal handling with threads

BUG FIXES:

## 1.3 (2017-09-01)

IMPROVEMENTS:
* handle errors more efficiently
* Update README.md
* update README

BUG FIXES:

## 1.2 (2017-01-01)

IMPROVEMENTS:
* add option to create progressive jpeg, close #11
* update debian/control file
* move page site to gh-pages branch
* code cleanup
* update site page
* update site page
* code cleanup
* code cleanup
* code cleanup
* code cleanup
* code cleanup
* code cleanup
* code cleanup
* code cleanup
* Merge branch 'dev' of github.com:llavaud/process-media into dev
* code cleanup and refactoring
* code cleanup
* update debian/control file

BUG FIXES:

## 1.1 (2016-10-21)

IMPROVEMENTS:
* if no creation date founded, keeping original name
* Merge branch 'dev'
* allow to specify custom video codec options, close #6
* update site page
* update site page
* update site page
* update site page
* update site page
* update site page
* update site page
* update site page index
* update site page index
* update site page index
* update site page
* update site page
* update site page
* remove stripping with exiftool on video, close #10

BUG FIXES:

## 1.0 (2016-10-06)

IMPROVEMENTS:
* update documentation
* update documentation
* code cleanup
* cleanup and refactoring
* change order of discovery for configuration file, local process-media.yaml is now read before any /etc/process-media.yaml
* allow to specify a strip_exclude for video (only support gps tag for now), close #9
* add new option strip_exclude in format definition and do some cleanup and refactoring
* add ffmpeg git version 20160928
* no longer need dependency on ffmpeg

BUG FIXES:

## 0.9 (2016-09-26)

IMPROVEMENTS:
* new version 0.9
* rename ffmpeg and ffprobe binary to avoid conflict with packaged version
* rename ffmpeg and ffprobe binary to avoid conflict with packaged version
* embed ffmpeg static binary version 3.1.3, close #8
* remove support of i386 architecture
* embed ffmpeg static binary version 3.1.3, close #8
* correcting a bug to get the audio codec
* debug problem with ffmpeg droping all metadata

BUG FIXES:

## 0.8 (2016-09-23)

IMPROVEMENTS:
* new package v0.8
* update README.md
* refactoring Video module
* correcting a bug with the video resize, now it is like for photo, resize is done only if larger than requested size, no upscaling
* allow all videos file with a mime type video/... in input, ffmpeg must support it

BUG FIXES:

## 0.7 (2016-09-21)

IMPROVEMENTS:
* new version 0.7
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* change the rotate format option to allow forced rotation
* update reprepro distribution file
* add dependency to libyaml-tiny-perl package
* remove .gitignore
* remove .gitignore
* Update README.md
* with separate modules required perl version is now 5.10

BUG FIXES:

## 0.6 (2016-09-13)

IMPROVEMENTS:
* new package 0.6
* correcting a bug with path of modules
* new package 0.5
* separate modules from main script
* update github pages
* Merge branch 'master' of github.com:llavaud/process-media
* update github pages
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md

BUG FIXES:

## 0.4 (2016-09-13)

IMPROVEMENTS:
* new package 0.4
* update debian repository
* add a .gitignore file
* update debian repository
* new package 0.3ubuntu1
* use /etc/process-media.yaml as default configuration file
* update debian repository
* update debian repository
* update debian repository
* update page site
* update page site
* update debian files
* add files to build debian/ubuntu package and personal repository
* Update index.html
* Create index.html
* integrate modules in script

BUG FIXES:

## 0.3 (2016-09-09)

IMPROVEMENTS:
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update README.md
* Update Readme.md
* update LICENSE
* cosmetics update
* refactoring and cosmetics update
* correcting bug with search_duplicate method
* refactoring and cosmetics update
* use mime types to detect file(s) to process, instead of regex on file extension
* correcting a bug with the compression of photo
* add a --batch option allowing to run in non-interactive mode, close #2
* allow to specify an absolute path for output_dir, close #3
* cosmetic update
* improve checks of command line parameters and config file options
* add comments to configuration file

BUG FIXES:

## 0.2 (2016-09-08)

IMPROVEMENTS:
* close #1
* remove a debug code line
* update dev branch
* update dev branch
* update dev branch
* update dev branch
* update dev branch
* update dev branch
* update dev branch
* update dev branch
* update dev branch
* update dev branch
* new version
* separate modules
* typo
* Update README.md

BUG FIXES:

## 0.1 (2016-09-02)

IMPROVEMENTS:
* Create README.md
* first version
* Initial commit

BUG FIXES:

