# Slide 07: Estimated transition interval from spatial derivatives

## Suggested slide message

Following the paper's criterion, transition is associated with the largest
positive chordwise derivative of the 2-7 kHz band level, Lp, or first spectral
moment, f_mu. With only eight microphones, the MMSA result is reported as the
adjacent-microphone interval containing that derivative, not as a precise point.

## How each bar is calculated

After sorting microphones from leading edge to trailing edge, the finite
difference for metric Q is

    D_i = (Q_(i+1) - Q_i) / (x_(i+1) - x_i),

where Q is either Lp or f_mu and x is x/c from the leading edge. Each bar is
placed at the midpoint of the corresponding adjacent-microphone interval.

- Gray bars: all other adjacent spatial slopes.
- Colored bar: largest positive slope selected by the criterion.
- Dashed line: midpoint of the selected interval; it is a visual guide, not a
  resolved transition coordinate.
- Text box: the actual x/c interval supported by the microphone spacing.

The paper interpolates its denser microphone measurements to 100 chordwise
points and locates the maximum derivative, with a second-derivative zero-crossing
and persistence checks. The MMSA adaptation uses measured adjacent finite
differences so that interpolation is not mistaken for additional spatial
resolution.

## Results to state

- 30 mph Lp: largest rise is between mic2 and mic1, x/c = 0.581-0.675.
- 30 mph f_mu: largest rise is one interval farther forward, between mic3 and
  mic2, x/c = 0.486-0.581.
- A conservative 30 mph candidate transition region therefore spans
  approximately x/c = 0.486-0.675; the spectral distribution changes before
  the full band energy reaches its large increase.
- 60 mph Lp and f_mu both select mic3-mic2, x/c = 0.486-0.581.
- The 60 mph agreement also overlaps the independently measured fluorescent
  line after conversion to leading-edge coordinates, but mic2 clipping can
  bias both metrics and especially f_mu.

## Interpretation limit

Call these intervals "acoustic transition estimates" or "candidate transition
zones." The derivatives identify where the measured spectrum changes fastest;
they do not independently prove the laminar and turbulent states.
