*KEYWORD
*TITLE
crash: thin-wall tube axial impact on rigid wall, 20kg tail mass, mm-ton-s
$
$ ============================= CONTROL =============================
$
*CONTROL_TERMINATION
$#  endtim    endcyc     dtmin    endeng    endmas     nosol
  4.000E-3         0       0.0       0.0   1.000E8         0
*CONTROL_ENERGY
$#    hgen      rwen    slnten     rylen
         2         2         2         2
*CONTROL_TIMESTEP
$#  dtinit    tssfac      isdo    tslimt     dt2ms      lctm     erode     ms1st
       0.0       0.9         0       0.0       0.0         0         0         0
*CONTROL_SHELL
$#  wrpang     esort     irnxx    istupd    theory       bwc     miter      proj
      20.0         1        -1         0         2         2         1         0
$
$ ============================= DATABASE =============================
$
*DATABASE_GLSTAT
$#      dt    binary      lcur     ioopt
  2.000E-5         1         0         1
*DATABASE_MATSUM
$#      dt    binary      lcur     ioopt
  2.000E-5         1         0         1
*DATABASE_RWFORC
$#      dt    binary      lcur     ioopt
  2.000E-5         1         0         1
*DATABASE_BINARY_D3PLOT
$#      dt      lcdt      beam     npltc    psetid
  2.000E-4         0         0         0         0
$
$ ============================= MATERIALS =============================
$
$ steel_mild (Q235/S235-class), mm-ton-s, from units.py material library
*MAT_PIECEWISE_LINEAR_PLASTICITY
$#     mid        ro         e        pr      sigy      etan      fail      tdel
         1  7.850E-9  2.100E+5       0.3     235.0    1200.0       0.0       0.0
$#       c         p      lcss      lcsr        vp
       0.0       0.0         0         0       0.0
$#    eps1      eps2      eps3      eps4      eps5      eps6      eps7      eps8
       0.0       0.0       0.0       0.0       0.0       0.0       0.0       0.0
$#     es1       es2       es3       es4       es5       es6       es7       es8
       0.0       0.0       0.0       0.0       0.0       0.0       0.0       0.0
$
$ ========================== SECTIONS / PARTS ==========================
$
*SECTION_SHELL
$#   secid    elform      shrf       nip     propt   qr/irid     icomp     setyp
         1        16  0.833333         5         1         0         0         1
$#      t1        t2        t3        t4      nloc     marea      idof    edgset
       1.5       1.5       1.5       1.5       0.0       0.0       0.0         0
*PART
$# title
tube steel_mild cylshell
$#     pid     secid       mid     eosid      hgid      grav    adpopt      tmid
         1         1         1         0         0         0         0         0
$
$ ========================== MESH INCLUDES ==========================
$
*INCLUDE
mesh_tube.k
$
$ ============================= CONTACT =============================
$
*SET_PART_LIST
$#     sid       da1       da2       da3       da4    solver
       801       0.0       0.0       0.0       0.0
$#    pid1      pid2      pid3      pid4      pid5      pid6      pid7      pid8
         1         0         0         0         0         0         0         0
*CONTACT_AUTOMATIC_SINGLE_SURFACE_ID
$#     cid                                                                 title
         1 tube self contact
$#   surfa     surfb  surfatyp  surfbtyp   saboxid   sbboxid      sapr      sbpr
       801         0         2         0         0         0         0         0
$#      fs        fd        dc        vc       vdc    penchk        bt        dt
       0.2       0.2       0.0       0.0       0.0         0       0.0       0.0
$#    sfsa      sfsb      sast      sbst     sfsat     sfsbt       fsf       vsf
       1.0       1.0       0.0       0.0       1.0       1.0       1.0       1.0
$#    soft    sofscl    lcidab    maxpar     sbopt     depth     bsort    frcfrq
         1       0.1         0     1.025         2         2         0         1
$
$ ========================= BOUNDARY / INITIAL =========================
$
$ Rigid wall: plane z=0.5, outward normal +z, friction 0.3, all nodes tracked
*RIGIDWALL_PLANAR
$#    nsid    nsidex     boxid    offset     birth     death     rwksf
         0         0         0       0.0       0.0  1.000E20       1.0
$#      xt        yt        zt        xh        yh        zh      fric      wvel
       0.0       0.0       0.5       0.0       0.0       1.5       0.3       0.0
$
$ Tail guidance: top ring (sid=16) constrained in x,y translation + all rot
*BOUNDARY_SPC_SET
$#    nsid       cid      dofx      dofy      dofz     dofrx     dofry     dofrz
        16         0         1         1         0         1         1         1
$
$ Initial axial velocity vz = -1.0e4 mm/s (10 m/s) for part 1
*INITIAL_VELOCITY_GENERATION
$#      id      styp     omega        vx        vy        vz     ivatn      icid
         1         2       0.0       0.0       0.0  -1.000E4         0         0
$#      xc        yc        zc        nx        ny        nz     phase    irigid
       0.0       0.0       0.0       0.0       0.0       0.0         0         0
$
$ ============================= LOADS =============================
$
$ Tail mass: 0.02 ton total, distributed to 48 top-ring nodes (sid=16),
$ 4.1667e-4 ton per node, eid 300001..300048
*ELEMENT_MASS
$#   eid     nid            mass     pid
  300001  101920      4.1667E-04       1
  300002  101921      4.1667E-04       1
  300003  101922      4.1667E-04       1
  300004  101923      4.1667E-04       1
  300005  101924      4.1667E-04       1
  300006  101925      4.1667E-04       1
  300007  101926      4.1667E-04       1
  300008  101927      4.1667E-04       1
  300009  101928      4.1667E-04       1
  300010  101929      4.1667E-04       1
  300011  101930      4.1667E-04       1
  300012  101931      4.1667E-04       1
  300013  101932      4.1667E-04       1
  300014  101933      4.1667E-04       1
  300015  101934      4.1667E-04       1
  300016  101935      4.1667E-04       1
  300017  101936      4.1667E-04       1
  300018  101937      4.1667E-04       1
  300019  101938      4.1667E-04       1
  300020  101939      4.1667E-04       1
  300021  101940      4.1667E-04       1
  300022  101941      4.1667E-04       1
  300023  101942      4.1667E-04       1
  300024  101943      4.1667E-04       1
  300025  101944      4.1667E-04       1
  300026  101945      4.1667E-04       1
  300027  101946      4.1667E-04       1
  300028  101947      4.1667E-04       1
  300029  101948      4.1667E-04       1
  300030  101949      4.1667E-04       1
  300031  101950      4.1667E-04       1
  300032  101951      4.1667E-04       1
  300033  101952      4.1667E-04       1
  300034  101953      4.1667E-04       1
  300035  101954      4.1667E-04       1
  300036  101955      4.1667E-04       1
  300037  101956      4.1667E-04       1
  300038  101957      4.1667E-04       1
  300039  101958      4.1667E-04       1
  300040  101959      4.1667E-04       1
  300041  101960      4.1667E-04       1
  300042  101961      4.1667E-04       1
  300043  101962      4.1667E-04       1
  300044  101963      4.1667E-04       1
  300045  101964      4.1667E-04       1
  300046  101965      4.1667E-04       1
  300047  101966      4.1667E-04       1
  300048  101967      4.1667E-04       1
*END
