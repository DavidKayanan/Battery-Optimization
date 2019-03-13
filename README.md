# Battery-Optimization

SIMPLE BATTERY ENERGY ARBITRAGE MODEL

Given a 24h hourly price profile, this demo optimizes the performance of the Tesla Powerwall to perform energy arbitrage 
(just one way a battery could provide value).

DEPENDENCIES
  - Python 3.6
  - Gurobi Python API 8.1
  - Pandas 0.23.4
  - Matplotlib 3.0.1
  - Seaborn 0.9.0

OPTIMIZATION FORMULATION

MIP, with a binary variable per hour to decide whether the battery should charge or discharge.

Decision variables:
  - E     stored charge [kWh],       Er*(1-DoD) < E < Er
  - Pch   Charging power [kW],       0 < Pch < Pr
  - Pdis  Discharge power [kW],      0 < Pdis < Pr
  - b     Charge/discharge decision (1 means charge)
  
  Pch, Pdis and b are vectors of length 24, whereas E is of length 24+1 to include the final charge. The initial charge must be restored
  at the end to remove bias.
  
Parameters:
  - Pr          Battery rated output
  - Er          Battery capacity
  - DoD         Recommended depth of discharge (determines lower bound for E)
  - eff_ch      Charging efficiency
  - eff_dis     Discharging efficiency (cycle effciency = eff_ch*eff_dis)
  - delta_t     Time step (1h in this case)
  - Price       Electricity price [monetary/kWh]
  
Constraints:
  - Charge balance          Et+1 = Et + (eff_ch*Pch_t - Pdis_t/eff_dis)*delta_t
  - Charge XOR Discharge    Pch_t/Pr + (1-b_t) <= 1,
                            Pdis_t/Pr + b_t <= 1
  - Restore initial charge  Init E = final E (but these two are decision variables)
  
Objective:
  max sum(Price(Pdis-Pch)*delta_t) for all t in period
