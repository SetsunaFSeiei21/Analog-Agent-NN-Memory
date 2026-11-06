* ltOpamp114 - independent cascode-bias branch, SKY130 1.8 V LVT.
* W/L in um under scale=1u.
* Original input mapping: in1 -> VINN; in2 -> VINP.
* New MNM11/12/13 become XNM11_BIAS/XNM12_BIAS/XNM13_BIAS.
* Original MNM_11/12/13 keep XNM11/XNM12/XNM13.

.include "ltOpamp114_params.sp"
.option scale=1u

.subckt DUT VINP VINN VOUT VDD VSS

* Reference current and NMOS reference mirror.
IBIAS_SRC VDD VBIAS DC {IBIAS_A}

XNM1 VBIAS VBIAS VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XNM7 N7    VBIAS VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1

* PMOS reference mirror.
XPM5  N7 N7 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m=1
XPM17 N1 N7 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m=1
XPM18 N0 N7 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m=1

* Tail-current reference and tail.
XNM2  N1 N1 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m=1
XNM10 N6 N1 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={2*DESVAR_M1}

* Independent cascode-bias string: N0 -> NET1 -> NET2 -> VSS.
* N1/NET1 and N2/NET2 are distinct nodes.
XNM11_BIAS N0   N0   NET1 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W8} L={DESVAR_L8} m=1
XNM12_BIAS NET1 NET1 NET2 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W9} L={DESVAR_L9} m={DESVAR_M3}
XNM13_BIAS NET2 NET1 VSS  VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W9} L={DESVAR_L9} m=1

* Matched input differential pair.
XNM12 N3 VINN N6 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M1}
XNM13 N5 VINP N6 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M1}

* Matched NMOS cascode pair.
XNM11 N2 N0 N3 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M1}
XNM9  N4 N0 N5 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M1}

* First-stage PMOS current-mirror load.
XPM6  N2 N2 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M1}
XPM16 N4 N2 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M1}

* Second stage.
XPM15 VOUT N4    VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M1*DESVAR_M2}
XNM8  VOUT VBIAS VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M1*DESVAR_M2}

* Miller compensation.
CC0 N4 VOUT {CCOMP_F}

.ends DUT