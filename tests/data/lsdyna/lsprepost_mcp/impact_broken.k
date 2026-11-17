*KEYWORD
*TITLE
L3 fixture: block above plate, units mm-t-s (mm, tonne, s, N, MPa)
*CONTROL_TERMINATION
$#  endtim    endcyc     dtmin    endeng    endmas
     1e-05         0       0.0       0.0       0.0
*DATABASE_BINARY_D3PLOT
$#      dt      lcdt      beam     npltc    psetid
     5e-05         0         0         0         0
*PART
plate
$#     pid     secid       mid     eosid      hgid      grav    adpopt      tmid
         1         1         1         0         0         0         0         0
*PART
block
         2         3         2         0         0         0         0         0
*SECTION_SOLID
$#   secid    elform       aet
         1         1         0
*MAT_ELASTIC
$#     mid        ro         e        pr        da        db  not used
         1  7.85e-09  210000.0       0.3       0.0       0.0         0
*MAT_ELASTIC
         2  7.85e-09  200000.0      0.29       0.0       0.0         0
*INCLUDE
impact_mesh.k
*END
