// IO7-only diagnostic for the mic4/mic5 module.
// This uses the proven two-channel PDM path while leaving the normal IO5 recorder unchanged.
// Fit mic4 before judging its channel; an empty PDM half-slot is high-impedance and is not valid audio.

#define MIC_DATA_PIN 7
#define WAV_PREFIX "IO7"
#define MIC_LEFT_INDEX 4
#define MIC_RIGHT_INDEX 5
#define RECORDER_LABEL "MMSA V2 IO7-only diagnostic"

#include "../MMSA_V2_StereoRecorder/MMSA_V2_StereoRecorder.ino"
