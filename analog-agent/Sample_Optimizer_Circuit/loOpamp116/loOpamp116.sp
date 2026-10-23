* ============================================================
* loOpamp116 - constrained sizing version
*
* Interface: DUT VINP VINN VOUT VDD VSS
* W/L: um under the Sky130 scale=1u convention.
*
* 21 independent parameters:
*   8 W + 8 L + 4 M + IBIAS_A
* ============================================================

.include "loOpamp116_params.sp"

.subckt DUT VINP VINN VOUT VDD VSS

* Reference current
IBIAS_SRC VDD VBIAS DC {IBIAS_A}

* ------------------------------------------------------------
* NMOS bias network
*
* Upper devices XNM0 / XNM6 share W1/L1.
* Lower devices XNM10 / XNM1 / XNM2 share W2/L2.
* XNM0 / XNM10 use M1; XNM1 / XNM6 use 2*M3+M4.
* XNM2 uses M2. All NMOS bulk terminals connect to VSS.
*
* Independent length groups:
*   L1: XNM0, XNM6
*   L2: XNM10, XNM1, XNM2
* ------------------------------------------------------------

XNM0  VBIAS VBIAS N0  VSS  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={DESVAR_M1}
XNM10 N0    N1    VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M1}

XNM1  N1    N1    VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={2*DESVAR_M3+DESVAR_M4}
XNM6  N3    VBIAS N1  VSS  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={2*DESVAR_M3+DESVAR_M4}

XNM2  N7    N1    VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M2}

* ------------------------------------------------------------
* Matched input differential pair
* ------------------------------------------------------------

XNM8  N4    VINP  N3  VSS  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M3}
XNM9  N2    VINN  N3  VSS  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M3}

* ------------------------------------------------------------
* Cascode bias: independent W4/L4; branch multiplier M4
* ------------------------------------------------------------

XNM3  N6    N6    N3  VSS  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M4}

* Matched cascode pair
XNM7  N5    N6    N4  VSS  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M3}
XNM5  VOUT  N6    N2  VSS  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M3}

* ------------------------------------------------------------
* PMOS bias mirror
* Shared W6/L6; nominal mirror ratio is M4/M2.
* ------------------------------------------------------------

XPM0  N7    N7    VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6}  L={DESVAR_L6} m={DESVAR_M2}
XPM3  N6    N7    VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M4}

* ------------------------------------------------------------
* PMOS active load
* XPM1 / XPM4 share W7/L7/M3.
* XPM2 has independent W8/L8 and shares multiplier M3.
* ------------------------------------------------------------

XPM1  N8    N8    VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M3}
XPM4  N5    N8    VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M3}

XPM2  VOUT  N5    N8  N8  sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W8} L={DESVAR_L8} m={DESVAR_M3}

.ends DUT