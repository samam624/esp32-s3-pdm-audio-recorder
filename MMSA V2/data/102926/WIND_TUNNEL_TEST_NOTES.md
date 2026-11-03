# First MMSA V2 Wind-Tunnel Test

**Test date:** October 29, 2026  
**Recorder:** MMSA V2 eight-microphone linear array  
**Purpose:** Verify recorder operation in a wind tunnel, compare covered and uncovered microphone response, and determine whether the array can resolve a flow-related high-pressure/high-noise region moving along a wing surface as tunnel speed increases.

## Test objectives

1. Confirm that all eight microphones record valid, synchronized audio before installation.
2. Characterize the array on the tunnel floor at 0, 30, and 60 mph, including both speed ramps.
3. Compare uncovered microphones with microphones protected by pop-filter material.
4. Mount the array on a wing and look for spatial changes in the surface-pressure/noise field as tunnel speed increases.
5. Inspect the array after each installation for damage, loose connections, or changed microphone behavior.

## Procedure

### 1. Pre-installation check

The array was recorded before installation to verify that every microphone channel was active and responding. A second short recording was made in the tunnel before the formal floor and wing runs.

### 2. Tunnel-floor installation

- The microphone array was placed on the wind-tunnel floor with the array oriented sideways relative to the tunnel flow.
- Firmware microphones **mic4** and **mic6** were covered with pop-filter material for the entire floor-test sequence.
- The other six microphones were left uncovered.
- Recordings were made under the following conditions:

| Take | Label | Condition |
|---:|---|---|
| 0003 | `Floor_0` | Tunnel off, baseline |
| 0004 | `Floor_0` | Second tunnel-off baseline |
| 0005 | `Floor_0_30` | Ramp from 0 to 30 mph |
| 0006 | `Floor_30` | Steady 30 mph |
| 0007 | `Floor_30_60` | Ramp from 30 to 60 mph |
| 0008 | `Floor_60` | Steady 60 mph |

After the floor sequence, the array was removed and inspected for problems.

### 3. Wing installation

- The microphone array was attached to the wing surface with tape.
- No microphones were covered with pop-filter material during the wing sequence.
- The array was installed at an angle; the leading-edge orientation was approximately **40 degrees**. The exact reference used for this angle should be recorded before using it in aerodynamic calculations.
- In this installation, **mic0 and mic1 were the two aftmost microphones**, with mic2 immediately forward of them along the array.
- Recordings were made under the following conditions:

| Take | Label | Condition |
|---:|---|---|
| 0009 | `Wing_0` | Tunnel off, baseline |
| 0010 | `Wing_0_30` | Ramp from 0 to 30 mph |
| 0011 | `Wing_30` | Steady 30 mph |
| 0012 | `Wing_30_60` | Ramp from 30 to 60 mph |
| 0013 | `Wing_60` | Steady 60 mph |

After the wing sequence, the array was removed and inspected for problems.

## Observation made during testing

The wing recordings showed a spatially localized high-level region. At the lower nonzero tunnel speed, the two aftmost microphones, mic0 and mic1, reached the highest levels first. As speed increased, mic2 also entered this high-level region. This downstream-to-upstream expansion is the type of spatial behavior the array was designed to detect.

The observation is consistent with a speed-dependent change in the local flow or boundary layer, potentially including a turbulent or transitional region, but the current recordings alone do not establish the aerodynamic cause. The result must be separated from microphone saturation, installation effects, local port response, and microphone-to-microphone sensitivity differences.

## Analysis approach

The processing uses firmware microphone numbers (`mic0` through `mic7`) and includes:

- WAV-format, channel-continuity, and clipping checks;
- 100 ms, 50%-overlapped level windows;
- broadband 20 Hz-20 kHz level;
- the recorder's five monitoring bands: 20-125 Hz, 125-500 Hz, 500 Hz-2 kHz, 2-8 kHz, and 8-20 kHz;
- wing heatmaps showing level versus time and microphone position;
- profiles comparing steady 0, 30, and 60 mph conditions; and
- a relative-level view showing which microphones lie within the high-level region in each window.

Outputs are written to [`analysis`](analysis/), and the reusable processor is [`wind_tunnel_analysis.py`](../../tools/wind_tunnel_analysis.py).

## Metadata still needed for aerodynamic interpretation

- The physical distance of each microphone from the leading edge, or enough geometry to calculate it.
- The direction in which microphone numbers increase on the wing.
- A precise definition of the approximately 40-degree angle.
- Tunnel-speed versus recording-time data for both ramp runs, including when each ramp began and ended.
- Airfoil/wing section, chord, angle of attack, and test-section dimensions.
- Air density, temperature, and static pressure, if available.
- Confirmation of the post-run microphone inspection result.
- At least one repeated wing run at each speed to establish repeatability.

