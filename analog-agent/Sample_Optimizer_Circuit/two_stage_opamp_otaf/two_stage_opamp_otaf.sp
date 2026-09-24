* SKY130 two-stage single-ended op amp converted from the Cadence topology.
* Testbench interface: VINP VINN VOUT VDD VSS.
* MOS W/L use micrometers under the SKY130 PDK scale=1u option.
* M1_FACTOR scales the first-stage devices and tail-current mirror.
* M2_FACTOR additionally scales both second-stage devices.

.include "two_stage_opamp_otaf_params.sp"

.subckt DUT VINP VINN VOUT VDD VSS

* Internal bias corresponding to Cadence MNM4 and II0.
IBIAS_SRC VDD VBIAS DC {IBIAS_A}
XMBIAS VBIAS VBIAS VSS VSS sky130_fd_pr__nfet_01v8 L={LBIAS} W={WBIAS} m=1

* First-stage tail device corresponding to Cadence MNM3.
XMTAIL NTAIL VBIAS VSS VSS sky130_fd_pr__nfet_01v8 L={LBIAS} W={WBIAS} m={2*M1_FACTOR}

* Stage 1: NMOS differential pair corresponding to Cadence MNM0/MNM2.
XMN_INN N1 VINN NTAIL VSS sky130_fd_pr__nfet_01v8 L={LIN} W={WIN} m={M1_FACTOR}
XMN_INP OTA_OUT VINP NTAIL VSS sky130_fd_pr__nfet_01v8 L={LIN} W={WIN} m={M1_FACTOR}

* PMOS current-mirror load corresponding to Cadence MPM0/MPM1.
XMP_DIODE N1 N1 VDD VDD sky130_fd_pr__pfet_01v8 L={LLOAD} W={WLOAD} m={M1_FACTOR}
XMP_MIRROR OTA_OUT N1 VDD VDD sky130_fd_pr__pfet_01v8 L={LLOAD} W={WLOAD} m={M1_FACTOR}

* Stage 2 corresponding to Cadence MNM5/MPM2.
* Both devices use the same effective multiplicity: (2*M1_FACTOR)*M2_FACTOR.
XMP_STAGE2 VOUT OTA_OUT VDD VDD sky130_fd_pr__pfet_01v8 L={L2P} W={W2P} m={(2*M1_FACTOR)*M2_FACTOR}
XMN_STAGE2 VOUT VBIAS VSS VSS sky130_fd_pr__nfet_01v8 L={LBIAS} W={WBIAS} m={(2*M1_FACTOR)*M2_FACTOR}

* Miller compensation: series nulling resistor and ideal capacitor.
RNULL OTA_OUT COMP {RNULL_OHM}
CCOMP COMP VOUT {CCOMP_F}

.ends DUT
