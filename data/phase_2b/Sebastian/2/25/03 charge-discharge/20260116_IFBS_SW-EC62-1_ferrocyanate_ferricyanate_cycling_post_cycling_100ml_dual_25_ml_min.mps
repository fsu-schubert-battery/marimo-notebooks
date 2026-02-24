EC-LAB SETTING FILE

Number of linked techniques : 6

EC-LAB for windows v11.61 (software)
Internet server v11.61 (firmware)
Command interpretor v11.61 (firmware)

Filename : C:\Users\IOMCguest\Desktop\Local Data\SW local\VMP3-42\SW-EC62-2\03 CD cycling\20260116_IFBS_SW-EC62-1_ferrocyanate_ferricyanate_cycling_post_cycling_100ml_dual_25_ml_min.mps

Device : VMP3
CE vs. WE compliance from -10 V to 10 V
Electrode connection : standard
Potential control : Ewe
Ewe ctrl range : min = -1.00 V, max = 1.00 V
Safety Limits :
	Do not start on E overload
Electrode material : Graphite
Initial state : SOC 50%
Electrolyte : Ferrocyanide/Ferricyanadie/KCl in water (0.1 mol/L, 0.1 mol/L, 1 mol/L)
Comments : low flow rate (3.3 ml/min)
Electrode surface area : 5.300 cm²
Characteristic mass : 0.001 g
Equivalent Weight : 0.000 g/eq.
Density : 0.000 g/cm3
Volume (V) : 0.001 cm³
Cycle Definition : Charge/Discharge alternance
Turn to OCV between techniques

Technique : 1
Galvanostatic Cycling with Potential Limitation
Ns                  0                   1                   2                   3                   
Set I/C             I                   I                   I                   I                   
Is                  0.000               400.000             -400.000            400.000             
unit Is             mA                  mA                  mA                  mA                  
vs.                 <None>              <None>              <None>              <None>              
N                   1.00                1.00                1.00                1.00                
I sign              > 0                 > 0                 > 0                 > 0                 
t1 (h:m:s)          0:00:0.0000         5:00:0.0000         5:00:0.0000         5:00:0.0000         
I Range             1 A                 1 A                 1 A                 1 A                 
Bandwidth           5                   5                   5                   5                   
dE1 (mV)            0.00                5.00                5.00                5.00                
dt1 (s)             0.0000              5.0000              5.0000              5.0000              
EM (V)              0.000               0.500               -0.500              0.000               
tM (h:m:s)          0:00:0.0000         0:00:0.0000         0:00:0.0000         2:00:0.0000         
Im                  0.000               0.250               0.000               0.250               
unit Im             mA                  mA                  mA                  mA                  
dI/dt               0.000               0.000               0.000               0.000               
dunit dI/dt         mA/s                mA/s                mA/s                mA/s                
E range min (V)     -1.000              -1.000              -1.000              -1.000              
E range max (V)     1.000               1.000               1.000               1.000               
dq                  0.000               1.000               1.000               1.000               
unit dq             A.h                 A.h                 A.h                 A.h                 
dtq (s)             0.0000              5.0000              120.0000            5.0000              
dQM                 0.000               0.000               0.000               0.000               
unit dQM            mA.h                mA.h                mA.h                mA.h                
dxM                 0.000               0.000               0.000               0.000               
delta SoC (%)       pass                pass                pass                pass                
tR (h:m:s)          0:05:0.0000         0:00:0.0000         0:00:0.0000         0:00:0.0000         
dER/dt (mV/h)       0.0                 0.0                 0.0                 0.0                 
dER (mV)            0.00                0.00                0.00                0.00                
dtR (s)             1.0000              10.0000             10.0000             10.0000             
EL (V)              pass                pass                pass                pass                
goto Ns'            0                   0                   1                   0                   
nc cycles           0                   0                   26                  0                   

Technique : 2
Open Circuit Voltage
tR (h:m:s)          0:10:0.0000         
dER/dt (mV/h)       0.0                 
record              <Ewe>               
dER (mV)            0.00                
dtR (s)             0.5000              
E range min (V)     -1.000              
E range max (V)     1.000               

Technique : 3
Potentio Electrochemical Impedance Spectroscopy
Mode                Single sine         
E (V)               0.0000              
vs.                 Eoc                 
tE (h:m:s)          0:00:0.0000         
record              0                   
dI                  0.000               
unit dI             mA                  
dt (s)              0.000               
fi                  200.000             
unit fi             kHz                 
ff                  10.000              
unit ff             mHz                 
Nd                  10                  
Points              per decade          
spacing             Logarithmic         
Va (mV)             10.0                
pw                  0.10                
Na                  2                   
corr                0                   
E range min (V)     -1.000              
E range max (V)     1.000               
I Range             Auto                
Bandwidth           5                   
nc cycles           2                   
goto Ns'            0                   
nr cycles           0                   
inc. cycle          0                   

Technique : 4
Open Circuit Voltage
tR (h:m:s)          0:10:0.0000         
dER/dt (mV/h)       0.0                 
record              <Ewe>               
dER (mV)            0.00                
dtR (s)             0.5000              
E range min (V)     -1.000              
E range max (V)     1.000               

Technique : 5
Chronopotentiometry
Ns                  0                   1                   2                   3                   4                   5                   6                   7                   8                   9                   10                  11                  12                  13                  14                  15                  16                  17                  18                  19                  20                  
Is                  0.000               80.000              0.000               -80.000             0.000               160.000             0.000               -160.000            0.000               240.000             0.000               -240.000            0.000               320.000             0.000               -320.000            0.000               400.000             0.000               -400.000            0.000               
unit Is             mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  mA                  
vs.                 <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              <None>              
ts (h:m:s)          0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         0:02:0.0000         
EM (V)              pass                0.800               pass                -0.800              pass                0.800               pass                -0.800              pass                0.800               pass                -0.800              pass                0.800               pass                -0.800              pass                0.800               pass                -0.800              pass                
dQM                 0.000               2.667               0.000               2.667               0.000               5.333               0.000               5.333               0.000               8.000               0.000               8.000               0.000               10.667              0.000               10.667              0.000               13.333              0.000               13.333              0.000               
unit dQM            mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                mA.h                
record              <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               <Ewe>               
dEs (mV)            0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                0.00                
dts (s)             0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              0.5000              
E range min (V)     -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              -1.000              
E range max (V)     1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               1.000               
I Range             1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 1 A                 
Bandwidth           5                   5                   5                   5                   5                   5                   5                   5                   5                   5                   5                   5                   5                   5                   5                   5                   5                   5                   5                   5                   5                   
goto Ns'            0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   
nc cycles           0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   0                   

Technique : 6
Open Circuit Voltage
tR (h:m:s)          100:00:0.0000       
dER/dt (mV/h)       0.0                 
record              <Ewe>               
dER (mV)            0.00                
dtR (s)             0.5000              
E range min (V)     -1.000              
E range max (V)     1.000               
