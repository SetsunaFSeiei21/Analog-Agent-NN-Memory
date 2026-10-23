* ============================================================
* loOpamp116 - constrained sizing version
*
* Interface: DUT VINP VINN VOUT VDD VSS
* W/L: um under the Sky130 scale=1u convention.
*
* 28 independent parameters:
*   10 W + 8 L + 9 M + IBIAS_A
* ============================================================

.include "loOpamp116_params.sp"

.subckt DUT VINP VINN VOUT VDD VSS

* Reference current
IBIAS_SRC VDD VBIAS DC {IBIAS_A}

* ------------------------------------------------------------
* NMOS bias network
*
* XNM0 / XNM10 share W and M.
* XNM1 / XNM6  share W and M.
*
* Independent length groups:
*   L1: XNM0, XNM6
*   L2: XNM10, XNM1, XNM2
* ------------------------------------------------------------

XNM0  VBIAS VBIAS N0  N0  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={DESVAR_M1}
XNM10 N0    N1    VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L2} m={DESVAR_M1}

XNM1  N1    N1    VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M2}
XNM6  N3    VBIAS N1  N1  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L1} m={DESVAR_M2}

XNM2  N7    N1    VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L2} m={DESVAR_M6}

* ------------------------------------------------------------
* Matched input differential pair
* ------------------------------------------------------------

XNM8  N4    VINP  N3  N3  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W10} L={DESVAR_L10} m={DESVAR_M10}
XNM9  N2    VINN  N3  N3  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W10} L={DESVAR_L10} m={DESVAR_M10}

* ------------------------------------------------------------
* Independently adjustable cascode bias
* ------------------------------------------------------------

XNM3  N6    N6    N3  N3  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M3}

* Matched cascode pair
XNM7  N5    N6    N4  N4  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M7}
XNM5  VOUT  N6    N2  N2  sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M7}

* ------------------------------------------------------------
* PMOS bias mirror
* Shared L/M; width ratio remains adjustable.
* ------------------------------------------------------------

XPM0  N7    N7    VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W4}  L={DESVAR_L4} m={DESVAR_M4}
XPM3  N6    N7    VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W14} L={DESVAR_L4} m={DESVAR_M4}

* ------------------------------------------------------------
* PMOS active load
* XPM1 / XPM4 share W/L/M.
* XPM2 remains independently adjustable.
* ------------------------------------------------------------

XPM1  N8    N8    VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M5}
XPM4  N5    N8    VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M5}

XPM2  VOUT  N5    N8  N8  sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W13} L={DESVAR_L13} m={DESVAR_M13}

.ends DUT