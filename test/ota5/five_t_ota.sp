* ============================================================
* five_t_ota.sp
* SKY130 Classic 5-Transistor OTA
*
* Pin order:
* VINP VINN VOUT VDD VSS VBIAS
*
* W/L units: um
* ============================================================

.subckt FIVE_T_OTA VINP VINN VOUT VDD VSS VBIAS params: WIN=20 LIN=0.5 WLOAD=40 LLOAD=0.5 WTAIL=8 LTAIL=0.5


* ============================================================
* NMOS differential pair
* ============================================================

XMN1 N1 VINP NTAIL VSS sky130_fd_pr__nfet_01v8
+ L={LIN}
+ W={WIN}

XMN2 VOUT VINN NTAIL VSS sky130_fd_pr__nfet_01v8
+ L={LIN}
+ W={WIN}


* ============================================================
* PMOS current mirror active load
* XMP1 diode-connected
* ============================================================

XMP1 N1 N1 VDD VDD sky130_fd_pr__pfet_01v8
+ L={LLOAD}
+ W={WLOAD}

XMP2 VOUT N1 VDD VDD sky130_fd_pr__pfet_01v8
+ L={LLOAD}
+ W={WLOAD}


* ============================================================
* NMOS tail current source
* ============================================================

XMTAIL NTAIL VBIAS VSS VSS sky130_fd_pr__nfet_01v8
+ L={LTAIL}
+ W={WTAIL}


.ends FIVE_T_OTA