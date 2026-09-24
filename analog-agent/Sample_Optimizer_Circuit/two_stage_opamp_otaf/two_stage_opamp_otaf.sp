* SKY130 two-stage single-ended op amp; first stage is a five-transistor OTA.
* Testbench interface: VINP VINN VOUT VDD VSS.
* MOS W/L use micrometers under the SKY130 PDK scale=1u option.
* Each M controls the number of parallel copies of its MOS group.

.include "two_stage_opamp_otaf_params.sp"

.subckt DUT VINP VINN VOUT VDD VSS

* Internal bias: reference current and the diode-connected NMOS are part of DUT.
IBIAS_SRC VDD VBIAS DC {IBIAS_A}
XMBIAS VBIAS VBIAS VSS VSS sky130_fd_pr__nfet_01v8 L={LBIAS} W={WBIAS}

* Stage 1: NMOS differential pair with PMOS current-mirror load.
* VINN drives the diode-load branch so that OTA_OUT is inverted from VINP.
XMIN1 N1 VINN NTAIL VSS sky130_fd_pr__nfet_01v8 L={LIN} W={WIN}
XMIN2 OTA_OUT VINP NTAIL VSS sky130_fd_pr__nfet_01v8 L={LIN} W={WIN}
XMPLOAD1 N1 N1 VDD VDD sky130_fd_pr__pfet_01v8 L={LLOAD} W={WLOAD}
XMPLOAD2 OTA_OUT N1 VDD VDD sky130_fd_pr__pfet_01v8 L={LLOAD} W={WLOAD}
XMTAIL NTAIL VBIAS VSS VSS sky130_fd_pr__nfet_01v8 L={LBIAS} W={WBIAS} m={M_TAIL1}

* Stage 2: PMOS common-source gain with an NMOS mirrored-current load.
* It inverts OTA_OUT again, so VINP is the non-inverting input of DUT.
XMPSTAGE2 VOUT OTA_OUT VDD VDD sky130_fd_pr__pfet_01v8 L={L2P} W={W2P}
XMNSTAGE2 VOUT VBIAS VSS VSS sky130_fd_pr__nfet_01v8 L={LBIAS} W={WBIAS} m={M_TAIL2}

* Miller compensation: series nulling resistor and ideal capacitor.
RNULL OTA_OUT COMP {RNULL_OHM}
CCOMP COMP VOUT {CCOMP_F}

.ends DUT
