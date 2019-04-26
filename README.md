# Battery-Optimization

### SIMPLE BATTERY ENERGY ARBITRAGE MODEL

This project allows you to valuate a grid scale battery's financial performance in your target market. You just need the price profile (preferrably over 1 year).

#### DEPENDENCIES
  - Python 3.6
  - Gurobi Python API 8.1
  - Pandas 0.23.4
  - Matplotlib 3.0.1
  - Seaborn 0.9.0

#### OPTIMIZATION FORMULATION

MIP, with a binary variable per hour to decide whether the battery should charge or discharge.

Decision Variable | Description | Notes
------------ | ------------- | -------------
**E** | stored charge [kWh] | _Er_* (1-_DoD_) < **E** < _Er_
**Pch** | Charging power [kW] | 0 < **Pch** < _Pr_
**Pdis**| Discharge power [kW]| 0 < **Pdis** < _Pr_
**b** | Charge/discharge decision| (1 means charge)

  **Pch**, **Pdis** and **b** are vectors of with the same length as the price vector, whereas **E** is of this length +1 to include the final charge. The initial charge must be restored at the end to remove bias.
  
  
  Parameters | Description
  ------------ | -------------
  _Pr_ | Battery rated power output [kW]
  _Er_ | Battery capacity [kWh]
  _DoD_ | Recommended depth of discharge (determines lower bound for E)
  _eff_ch_ | Charging efficiency
  _eff_dis_ | Discharging efficiency (cycle effciency = _eff_ch_* _eff_dis_)
  _delta_t_ | Time step (1h in this case)
  **Price** | Electricity price [USD/kWh]
  
  <table>
    <thead>
        <tr>
            <th>Constraints</th>
            <th>&nbsp; </th>
        </tr>
    </thead>
    <tbody>
        <tr>         
            <td>Charge balance</td>
            <td>Et+1 = Et + (<i>eff_ch</i>* Pch_t - Pdis_t/<i>eff_dis</i>)* <i>delta_t</i></td>
        </tr>
        <tr>
            <td rowspan=2>Charge XOR Discharge</td>
            <td>Pch_t/ <i>Pr</i> + (1-b_t) <= 1 </td>
        </tr>
        <tr>
            <td>Pdis_t/ <i>Pr</i> + b_t <= 1 </td>
        </tr>
        <tr>
          <td> Restore initial charge </td>
          <td> Init E = final E (but these two are decision variables) </td>
        </tr>
    </tbody>
</table>

**Objective**    
**max** sum(Price(Pdis-Pch)* _delta_t_) for all t in period
