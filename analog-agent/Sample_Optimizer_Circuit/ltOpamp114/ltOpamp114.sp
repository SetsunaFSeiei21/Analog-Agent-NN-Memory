* ============================================================
* load_to_114 - Sky130 1.8-V two-stage operational amplifier
*
* Interface: DUT VINP VINN VOUT VDD VSS
* W/L: um under the Sky130 scale=1u convention.
*
* Original input mapping:
*   in1 -> VINN
*   in2 -> VINP
*
* 21 independent parameters:
*   8 W + 8 L + 3 M + CCOMP_F + IBIAS_A
* ============================================================

.include "ltOpamp114.sp"

.subckt DUT VINP VINN VOUT VDD VSS

* Reference current
IBIAS_SRC VDD VBIAS DC {IBIAS_A}

* NMOS reference mirror
XNM1 VBIAS VBIAS VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XNM7 N7 VBIAS VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1

* PMOS reference mirror
XPM5 N7 N7 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m=1
XPM17 N2 N7 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m=1
XPM18 N0 N7 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m=1

* Tail-current reference and mirror
XNM2 N2 N2 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m=1
XNM10 N1 N2 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={1+2*DESVAR_M1}

* Independent cascode-bias device
* M3 adjusts the bias voltage; XPM18 supplies the branch current.
XNM4 N0 N0 N1 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W8} L={DESVAR_L8} m={DESVAR_M3}

* Matched input differential pair
XNM12 N4 VINN N1 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M1}
XNM13 N6 VINP N1 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M1}

* Matched NMOS cascode pair
XNM11 N3 N0 N4 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M1}
XNM9 N5 N0 N6 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M1}

* First-stage PMOS current-mirror load
XPM6 N3 N3 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M1}
XPM16 N5 N3 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M1}

* Second stage
* XNM8 retains your W3/L3 grouping and VBIAS gate connection.
XPM15 VOUT N5 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M2*DESVAR_M1}
XNM8 VOUT VBIAS VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M2*DESVAR_M1}

* Miller compensation
CC0 N5 VOUT {CCOMP_F}

.ends DUT