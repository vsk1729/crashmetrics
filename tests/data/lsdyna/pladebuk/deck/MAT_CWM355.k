$# LS-DYNA Keyword file created by LS-PrePost(R) 2024/R2(4.11.14)-25Feb2025
$# Created on Apr-17-2026 (14:08:34)
*KEYWORD  

*MAT_CWM_TITLE
Benny_Bertel_Model
$#     mid        ro      lcem      lcpr      lcsy      lchr      lcat      beta
         17.85000E-9       411       412       413       414       415       0.0
$# tastart     taend   tlstart     tlend    eghost    pghost    aghost
    1331.0    1773.0-1.00000E8  -1000000   10000.0     0.2841.0000E-20
$# t2phase   t1phase     anopt     postv
       0.0       0.0       0.0         0
*MAT_THERMAL_CWM_TITLE
Plates_thermal
$#    tmid       tro     tgrlc    tgmult     hdead     tdead      tlat      hlat
         1       0.0       0.0       0.0       0.0       0.0       0.0       0.0
$#    lchc      lctc   tlstart     tlend   tistart     tiend    hghost    tghost
       211       212   -1000.0   -1000.0       0.0       0.06.500000E8     0.001
*DEFINE_CURVE_TITLE
LCHC
$#    lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint
       211         0       1.0       1.0       0.0       0.0         0         0
$#                a1                  o1
                 0.0    4.7000000000e+08
               273.0    4.7000000000e+08
               373.0    5.0500000000e+08
               473.0    5.2100000000e+08
               573.0    5.3400000000e+08
               673.0    5.4900000000e+08
               873.0    5.8700000000e+08
              1073.0    6.1400000000e+08
              1473.0    6.8800000000e+08
              1773.0    7.1200000000e+08
              9773.0    7.1200000000e+08
*DEFINE_CURVE_TITLE
LCTC
$#    lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint
       212         0       1.0       1.0       0.0       0.0         0       200
$#                a1                  o1
                 0.0                52.0
               273.0                52.0
               373.0                53.8
               473.0                57.3
               573.0                63.8
               673.0                64.1
               873.0                74.1
              1073.0                85.1
              1473.0               114.7
              1773.0               427.4
              9773.0               427.4
*DEFINE_CURVE_TITLE
LCEM
$#    lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint
       411         0       1.0       1.0       0.0       0.0         0         0
$#                a1                  o1
                 0.0            200000.0
               273.0            200000.0
               373.0            194458.0
               573.0            177329.0
               673.0            168261.0
               873.0            160201.0
              1073.0            152141.0
              1473.0             60453.0
              1773.0             10075.0
              9773.0             10075.0
*DEFINE_CURVE_TITLE
LCPR
$#    lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint
       412         0       1.0       1.0       0.0       0.0         0         0
$#                a1                  o1
                 0.0               0.290
               273.0               0.290
               373.0               0.291
               573.0               0.306
               673.0               0.314
               873.0               0.322
              1073.0               0.328
              1473.0               0.334
              1773.0               0.383
              9773.0               0.383
*DEFINE_CURVE_TITLE
LCSY
$#    lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint
       413         0       1.0       1.0       0.0       0.0         0         0
$#                a1                  o1
                 0.0               355.0
               273.0               355.0
               373.0               292.0
               573.0               227.0
               673.0               207.0
               873.0               199.0
              1073.0               121.0
              1473.0                33.0
              1773.0                13.0
              9773.0                13.0
*DEFINE_CURVE_TITLE
LCHR
$#    lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint
       414         0       1.0       1.0       0.0       0.0         0         0
$#                a1                  o1
                 0.0               350.0
               273.0               350.0
               373.0               300.0
               473.0               250.0
               573.0               150.0
               673.0               100.0
               873.0                55.0
              1073.0                10.0
              1773.0                 1.0
              9773.0                 1.0
*DEFINE_CURVE_TITLE
LCAT
$#    lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint
       415         0       1.0       1.0       0.0       0.0         0         0
$#                a1                  o1
                 0.0    1.2000000000e-05
               273.0    1.2000000000e-05
               373.0    1.2282400000e-05
               573.0    1.3129400000e-05
               673.0    1.3482400000e-05
               873.0    1.3835300000e-05
              1073.0    1.4258800000e-05
              1473.0    1.4611800000e-05
              1773.0    1.5247100000e-05
              9773.0    1.5247100000e-05
$*DEFINE_CURVE_TITLE
$LCLAT
$#    lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint
$      1001         0       1.0       1.0       0.0       0.0         0         0
$#                a1                  o1
$                 0.0                0.25
$              1000.0                0.25
*END
