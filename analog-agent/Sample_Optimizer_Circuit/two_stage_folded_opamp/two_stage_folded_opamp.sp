* SKY130 two-stage folded-cascode single-ended op amp.
* Converted from the Cadence topology without changing device connections.
* Testbench interface: VINP VINN VOUT VDD VSS.
* MOS W/L use micrometers under the SKY130 PDK scale=1u option.
* M1_FACTOR scales the folded-cascode signal-path devices.
* M2_FACTOR additionally scales both second-stage output devices.

.include "two_stage_folded_opamp_params.sp"

.subckt DUT VINP VINN VOUT VDD VSS

* Internal PMOS bias branch corresponding to Cadence MPM1 and II0.
* The reference current flows from VBP1 to VSS and is a design variable.
IBIAS_SRC VBP1 VSS DC {IBIAS_A}
XMP_BIAS_REF VBP1 VBP1 VDD VDD sky130_fd_pr__pfet_01v8 L={LPBIAS} W={WPBIAS} m=1

* Additional PMOS bias devices corresponding to Cadence MPM0/MPM4.
XMP_VB3 VB3 VBP1 VDD VDD sky130_fd_pr__pfet_01v8 L={LPBIAS} W={WPBIAS} m=1
XMP_VB2 VB2 VBP1 VDD VDD sky130_fd_pr__pfet_01v8 L={LPBIAS} W={WPBIAS} m=1

* PMOS bias stack corresponding to Cadence MPM2/MPM3.
XMP_PCAS_DIODE VB1 VB1 N_PBIAS VDD sky130_fd_pr__pfet_01v8 L={LPCAS_BIAS} W={WPCAS_BIAS} m=1
XMP_PCAS_SOURCE N_PBIAS VB1 VDD VDD sky130_fd_pr__pfet_01v8 L={LPCAS_BIAS} W={WPCAS_BIAS} m=1

* NMOS bias devices corresponding to Cadence MNM0/MNM1.
XMN_BIAS_REF VB3 VB3 VSS VSS sky130_fd_pr__nfet_01v8 L={LNBIAS} W={WNBIAS} m=1
XMN_VB1 VB1 VB3 VSS VSS sky130_fd_pr__nfet_01v8 L={LNBIAS} W={WNBIAS} m=1

* NMOS cascode-bias stack corresponding to Cadence MNM2/MNM3.
XMN_NCAS_DIODE VB2 VB2 N_NBIAS VSS sky130_fd_pr__nfet_01v8 L={LNCAS_BIAS} W={WNCAS_BIAS} m=1
XMN_NCAS_SOURCE N_NBIAS VB2 VSS VSS sky130_fd_pr__nfet_01v8 L={LNCAS_BIAS} W={WNCAS_BIAS} m=1

* PMOS input-pair tail source corresponding to Cadence MPM5.
XMP_INPUT_TAIL N_INPUT_TAIL VBP1 VDD VDD sky130_fd_pr__pfet_01v8 L={LPBIAS} W={WPBIAS} m={2*M1_FACTOR}

* PMOS differential pair corresponding to Cadence MPM6/MPM7.
XMP_INN N_FOLD_N VINN N_INPUT_TAIL VDD sky130_fd_pr__pfet_01v8 L={LIN} W={WIN} m={M1_FACTOR}
XMP_INP N_FOLD_P VINP N_INPUT_TAIL VDD sky130_fd_pr__pfet_01v8 L={LIN} W={WIN} m={M1_FACTOR}

* PMOS folded branches corresponding to Cadence MPM8/MPM9.
XMP_FOLD_P N_PCAS_P N_PCAS_GATE VDD VDD sky130_fd_pr__pfet_01v8 L={LPFOLD} W={WPFOLD} m={M1_FACTOR}
XMP_FOLD_N N_PCAS_N N_PCAS_GATE VDD VDD sky130_fd_pr__pfet_01v8 L={LPFOLD} W={WPFOLD} m={M1_FACTOR}

* PMOS cascodes corresponding to Cadence MPM10/MPM11.
XMP_CAS_P OTA_OUT VB1 N_PCAS_P VDD sky130_fd_pr__pfet_01v8 L={LPCAS} W={WPCAS} m={M1_FACTOR}
XMP_CAS_N N_PCAS_GATE VB1 N_PCAS_N VDD sky130_fd_pr__pfet_01v8 L={LPCAS} W={WPCAS} m={M1_FACTOR}

* NMOS sink devices corresponding to Cadence MNM5/MNM7.
XMN_SINK_P N_FOLD_P VB3 VSS VSS sky130_fd_pr__nfet_01v8 L={LNBIAS} W={WNBIAS} m={2*M1_FACTOR}
XMN_SINK_N N_FOLD_N VB3 VSS VSS sky130_fd_pr__nfet_01v8 L={LNBIAS} W={WNBIAS} m={2*M1_FACTOR}

* NMOS cascodes corresponding to Cadence MNM4/MNM6.
XMN_CAS_P OTA_OUT VB2 N_FOLD_P VSS sky130_fd_pr__nfet_01v8 L={LNCAS} W={WNCAS} m={M1_FACTOR}
XMN_CAS_N N_PCAS_GATE VB2 N_FOLD_N VSS sky130_fd_pr__nfet_01v8 L={LNCAS} W={WNCAS} m={M1_FACTOR}

* Second stage corresponding to Cadence MPM12/MNM8.
XMP_STAGE2 VOUT OTA_OUT VDD VDD sky130_fd_pr__pfet_01v8 L={L2P} W={W2P} m={M1_FACTOR*M2_FACTOR}
XMN_STAGE2 VOUT VB3 VSS VSS sky130_fd_pr__nfet_01v8 L={LNBIAS} W={WNBIAS} m={M1_FACTOR*M2_FACTOR}

* Miller compensation corresponding to Cadence RR0/CC0.
RNULL OTA_OUT COMP {RNULL_OHM}
CCOMP COMP VOUT {CCOMP_F}

.ends DUT
