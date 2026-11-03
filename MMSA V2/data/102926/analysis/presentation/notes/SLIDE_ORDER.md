# Presentation order and dependencies

## Dependency map

    context: hardware / installation / live acquisition
                              |
                broadband level timeline + ramp spectrograms
                              |
                    steady 30/60 broadband PSD
                              |
                   full-scale clipping by condition
                              |
                    02 array geometry photo
                              |
    00 frequency bands        |        01 flow reference photo
              |               |                 |
              +---------------+------- 03 shared x/c overlay
                                      |
                          04 steady-60 level profile
                                      |
                          05 30-vs-60 speed comparison
                                      |
                         context: clipping limitation
                                      |
                 06 paper-style Lp/f_mu profiles
                                      |
                           07 spatial derivatives
                                      |
                         context: key takeaways

## Slide sequence

### Context - Wind-tunnel hardware and acquisition

Uses selected test photographs rather than every image in the archive. IMG_6670
shows the assembled array and controller before installation, IMG_6678 shows the
array on the wing, and IMG_6674 shows the live eight-channel band-level display.
This slide establishes how the hardware, installation, and recorded data connect.

### Context - Wing-run broadband level timeline

Shows the uncalibrated 20 Hz-20 kHz level for every microphone over all five
wing takes. It introduces the raw progression from tunnel-off through the two
ramps and steady 30/60 mph conditions before any frequency-band choice or
transition interpretation is applied.

### Context - Ramp spectrograms

Shows the measured time-frequency content of mic0-mic3 during takes 0010 and
0012. The horizontal axis is recording time only. No linear speed-time mapping
is assumed, and no inferred high-level-zone marker is drawn.

### Context - Steady 30/60 mph broadband PSD

Uses the complete steady Wing 30 and Wing 60 recordings and the same 2048-point
Hann-window Welch estimator as the paper-style analysis. The matched panels show
all eight microphones over 20 Hz-20 kHz. They establish that the mic0/mic1 to
mic2 progression is broadband rather than an artifact of the selected 4-8 kHz
watch band. The 60 mph mic0-mic2 spectra remain clipping-limited.

### Context - Full-scale clipping by microphone and condition

Uses the raw PCM samples directly rather than a spectral-peak proxy. The top
panel counts distinct contiguous full-scale events per second; the lower panel
reports the percentage of samples at -32768 or +32767. The percentage makes
takes of different duration comparable, while the event rate distinguishes
many repeated impacts from one sustained clipped interval. Floor and wing runs
are included together. The underlying values are in
`full_scale_clipping_by_condition.csv`.

### 00 - Frequency-band comparison

Uses only the 30-60 mph WAV recording and time-domain band levels. It motivates
4-8 kHz as the preferred MMSA monitoring band and does not depend on image
registration or microphone x/c coordinates.

### 01 - 60 mph fluorescent flow visualization

Introduces the independent physical reference. The fluorescent-line position is
measured after normalizing the visible aft and forward wing edges to a chord
coordinate. The photograph stays in its native orientation, so the conventional
leading-edge x/c labels decrease from 1.00 at the aft edge on the left to 0.00
at the forward edge on the right, matching the rectified-array coordinate.

### 02 - Rectified MMSA array photograph

Introduces the measurement geometry. Each microphone port center is measured in
image pixels. The visible wing edges vary slightly with image row, so the image
is rectified row by row before each port is converted to x/c. Neutral markers
show the measured centers and each label gives the leading-edge x/c value used
by the later plots; no acoustic classification colors are applied yet.

### 03 - Flow/array overlay on a shared chord axis

Depends on slides 01 and 02. Both photographs are normalized between their
measured aft and forward edges. This establishes the microphone chord positions
used by every later x/c plot and shows that the fluorescent line lies in the
mic2-mic3 interval.

### 04 - Steady 60 mph level profile

Depends on slides 00 and 03: slide 00 supplies the 4-8 kHz band choice, while
slide 03 supplies the microphone x/c coordinates. It shows the measured level
break at the independently observed fluorescent-line location.

### 05 - 30 versus 60 mph, 4-8 kHz

Depends on slides 00 and 03 and extends slide 04. It shows the spatial break
moving forward from the mic1-mic2 region at 30 mph toward the mic2-mic3 region
at 60 mph.

### Context - Live clipping warning

Placed immediately before the paper-style metrics because it qualifies their
interpretation. IMG_6674 shows the normal live level table and IMG_6675 shows
the explicit clipping warning observed during testing. At 60 mph, mic0-mic2
clip, so the 30 mph result is the cleaner quantitative case and the 60 mph
metric magnitudes require caution.

### 06 - Paper-style 2-7 kHz Lp and f_mu profiles

Depends on the x/c registration established by slides 02-03. The 2-7 kHz range
comes from the paper's method, not from the 4-8 kHz empirical band selection on
slide 00. Dots are measured microphones; smooth curves are visual guides only.

### 07 - Spatial derivatives and candidate transition intervals

Depends directly on slide 06. Adjacent finite differences of Lp and f_mu are
divided by the corresponding x/c spacing. The largest positive slope selects a
measured microphone interval as the acoustic transition estimate.

### Context - Wind-tunnel takeaways

Uses IMG_6676 as a closing installation view beside the three defensible
conclusions: 4-8 kHz gives the clearest empirical separation; the fluorescent
boundary and acoustic break both occupy the mic2-mic3 interval at 60 mph; and
the paper-style derivative method reports x/c = 0.486-0.581 at the available
microphone spacing.

## Selected photographs

- IMG_6670: assembled array and controller before installation.
- IMG_6674: live multiband recording display.
- IMG_6675: live clipping warning and affected-channel display.
- IMG_6676: installed setup used on the closing slide.
- IMG_6678: strongest overall installation photograph.

The other archive images are retained as source material but omitted because
they are redundant, less legible, or show intermediate handling rather than a
distinct part of the argument.

## Coordinate provenance

The microphone chord coordinates are not inferred from the acoustic levels.
They come from the array photograph: manually measured microphone port centers
and wing-edge lines are converted to normalized chord position. The flow photo
is independently normalized using its own visible wing edges. Registration is
chordwise only; spanwise alignment and camera perspective remain approximate.

## File naming (2026-11-01)

The PNGs/JPGs in the parent folder are numbered 01-16 in dependency order, one
image per slide, so they can be pasted into Google Slides in sequence. The
section names above (context / 00-07) map to the numbered files by content.
