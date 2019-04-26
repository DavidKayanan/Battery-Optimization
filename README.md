# Battery-Optimization

### SIMPLE BATTERY ENERGY ARBITRAGE MODEL

This project allows you to **valuate a grid scale battery's financial performance** in your target market. You just need the price profile (preferrably over 1 year). The Jupyter notebook "Tesla Power Pack valuation in CAISO" walks you through how this project is used, and also includes all the plotting and analysis functionalities developed.

##### Features
1. Given a price vector, optimize a battery performing energy arbitrage only.
1. The net earnings is determine, and can be broken down to energy revenue and costs per month.
1. The 24h operation of the battery on a particular day can be viewed (along with prices)
1. A simple financial analysis is scripted at the end, assuming fixed revenues and costs. Use the indicative values for energy revenue and costs, and assume a revenue for ancilliary services.

___
#### 1 DEPENDENCIES
  - Python 3.6
  - Gurobi Python API 8.1
  - Pandas 0.23.4
  - Matplotlib 3.0.1
  - Seaborn 0.9.0

___
#### 2 OPTIMIZATION FORMULATION

MIP, with a binary variable per time step to decide whether the battery should charge or discharge. Gurobi is able to solve the 1-year MIP by cutting the root node, without descending the search tree.

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
  
  The first five parameters define the battery, and are stored in the `BatteryDefns` DataFrame (for simplicity, the cycle efficiency is the saved parameter, with the assumption that _eff_ch_ =  _eff_dis_).
  
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

___
#### 3 MARKET TIME IMPLEMENTATION
batopt.py depends on markettime.py `import markettime as mt`, which holds the classes to implement various time formats. For more information on the market time protocol, pls. refer to "markettime protocol.ipynb", as well as further below.

**CAISO Time Format**
Currently, only the CAISO format is defined (class `CAISO`, with a predefined instance `CA_time` loaded in batopt.py). The CAISO format defines a 24-hour market, starting from H01-H24, and implements DST switches with a 23-hour day on the switch to summer and a 25-hour day on the switch back to winter (defining H25, the very last hour of summer time). To define your own time in the CAISO format, pls. refer to the initialization of `CA_time` in cell 2 of "markettime protocol.ipynb".

**Basic idea behind market time**
1. The price vector in batopt's `self.prices` is interpretted as an iterable *without* time information (if this is a Pandas Series, the index is not used).
1. Time is inferred by providing the start time when you load prices.  
`battery.set_prices(Prices_CAISO['USD/kWh'], start_time=("01/01/2018", 1), market_time=CA_time)`
1. Whereas local time may switch timezones during DST, the time vector can be defined on a specified time zone (GMT, in this case). The Python index of `self.prices` then corresponds 1:1 on a GMT-based time vector.
1. It is then up to the market time implementation to convert GMT time into the local time (consider formats (i.e. H00-H23 or H01-H24), and DST). Class `batopt` defines methods `Market_toIdx()` and `Idx_toMarket()` for this, which wraps methods of the market time implementation.

