*KEYWORD
*TITLE
cold start: steel ball drop onto aluminum plate (mm-ton-s)
*CONTROL_TERMINATION
3.0000E-03         00.0000E+000.0000E+001.0000E+08         0
*CONTROL_ENERGY
         2         2         2         2
*CONTROL_TIMESTEP
0.0000E+009.0000E-01         00.0000E+000.0000E+00         0         0         0
*DATABASE_GLSTAT
1.5000E-05
*DATABASE_MATSUM
1.5000E-05
*DATABASE_BINARY_D3PLOT
1.5000E-04
*MAT_PIECEWISE_LINEAR_PLASTICITY
         12.7000E-096.8900E+043.3000E-012.7600E+026.0000E+020.0000E+000.0000E+00
0.0000E+000.0000E+00         0         00.0000E+00
0.0000E+000.0000E+000.0000E+000.0000E+000.0000E+000.0000E+000.0000E+000.0000E+00
0.0000E+000.0000E+000.0000E+000.0000E+000.0000E+000.0000E+000.0000E+000.0000E+00
*MAT_RIGID
         27.8500E-092.1000E+053.0000E-010.0000E+000.0000E+000.0000E+00          
1.0000E+00         4         7
0.0000E+000.0000E+000.0000E+000.0000E+000.0000E+000.0000E+00
*SECTION_SHELL
         1        161.0000E+00         51.0000E+00         0         0         1
2.0000E+002.0000E+002.0000E+002.0000E+000.0000E+000.0000E+000.0000E+00         0
*SECTION_SOLID
         2         1         0
*PART
aluminum plate 150x150x2mm
         1         1         1         0         0         0         0         0
*PART
rigid steel ball r8 (50 mm drop)
         2         2         2         0         0         0         0         0
*INCLUDE
mesh_plate.k
*INCLUDE
mesh_ball.k
*INITIAL_VELOCITY_GENERATION
         2         20.0000E+000.0000E+000.0000E+00-4.000E+03         0         0
0.0000E+000.0000E+000.0000E+000.0000E+000.0000E+000.0000E+00         0         0
*BOUNDARY_SPC_SET
        15         0         1         1         1         1         1         1
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE
         2         1         3         3         0         0         0         0
2.0000E-012.0000E-010.0000E+000.0000E+000.0000E+00         00.0000E+000.0000E+00
1.0000E+001.0000E+000.0000E+000.0000E+001.0000E+001.0000E+001.0000E+001.0000E+00
         11.0000E-01         01.0250E+00         2         2         0         1
*LOAD_BODY_Z
       9011.0000E+00         00.0000E+000.0000E+000.0000E+00         0
*DEFINE_CURVE
       901         01.0000E+001.0000E+000.0000E+000.0000E+00         0         0
          0.0000E+00          9.8100E+03
          1.0000E+00          9.8100E+03
*END
