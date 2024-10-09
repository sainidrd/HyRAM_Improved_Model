"""
Copyright 2015-2021 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights in this software.

You should have received a copy of the GNU General Public License along with HyRAM+.
If not, see https://www.gnu.org/licenses/.
"""

from __future__ import print_function, absolute_import, division

import copy

import numpy as np
from scipy import optimize

from ._comps import Orifice


class NotionalNozzle:
    def __init__(self, fluid_orifice, orifice, low_P_fluid):
        '''Notional nozzle class'''
        self.fluid_orifice, self.orifice, self.low_P_fluid = fluid_orifice, orifice, low_P_fluid
    
    def calculate(self, T = 'solve_energy', conserve_momentum = True):
        '''
        Calculates the properties after the notional nozzle using one of the following models:
        
        Parameters
        ----------
        T: string ('solve_energy', or 'Tthroat' - if conserve_momentum is false) or value
            how to calculate or specify temperature at end of notional nozzle
        conserve_momentum: boolean
            whether to use conservation of momentum equation
        Literature references for models of different combinations are:
            YuceilOtugen - conserve_momentum = True, T = solve_energy
            EwanMoodie - conserve_momentum = False, T = Tthroat
            Birch - conserve_momentum = False, T = T0
            Birch2 - conserve_momentum = True, T = T0
            Molkov - conserve_momentum = False, T = solve_energy
        
        Returns
        -------
        tuple of (fluid object, orifice object), all at exit of notional nozzle
        '''
        throat = self.fluid_orifice
        if conserve_momentum:
            #YuceilOtugen, Birch2
            v = throat.v + (throat.P - self.low_P_fluid.P)/(throat.v*throat.rho*self.orifice.Cd) 
            # from Momentum conservation P_2 + rho_2*V_2^2 = P_3 + rho_3*V_3^2
            # replace rho_3*V_3  = rho_2*V_2
            # V_3 = P_2-P_3/rho_2*V_2 + V_2
            if T == 'solve_energy':
                #YuceilOtugen
                rho = optimize.brentq(lambda rho: throat.therm._err_H_P_rho(throat.P, throat.rho, throat.v,
                                                                            self.low_P_fluid.P, rho, v), 
                                      throat.rho, throat.therm.rho(self.low_P_fluid.T, self.low_P_fluid.P))
                #print("Notional nozzle rho=", rho)
                T = throat.therm.T(self.low_P_fluid.P, rho)
            elif np.isreal(T):
                #Birch2 - T specified as T0
                rho = throat.therm.rho(T, self.low_P_fluid.P)
            else:
                raise NotImplementedError('Notional nozzle model not defined properly, ' + 
                                          "nn_T must be specified temperature or 'solve_energy'.")
        else:
            #EwanMoodie, Birch, Molkov -- assume sonic at notional nozzle location
            if np.isreal(T):
                # Birch: T specified as T0
                v = throat.therm.a(T = T, P = self.low_P_fluid.P)
                rho = throat.therm.rho(T = T, P = self.low_P_fluid.P)
            elif T == 'Tthroat':
                #EwanMoodie - T is Throat temperature
                v = throat.therm.a(T = throat.T, P = self.low_P_fluid.P)
                rho = throat.therm.rho(T = throat.T, P = self.low_P_fluid.P)
            elif T == 'solve_energy':
                #Molkov
                def err(rho):
                    T = throat.therm.T(P = self.low_P_fluid.P, rho = rho)
                    v = throat.therm.a(T = T, P = self.low_P_fluid.P)
                    return throat.therm._err_H_P_rho(throat.P, throat.rho, throat.v,
                                                     self.low_P_fluid.P, rho, v)
                rho = optimize.newton(err, throat.therm.rho(self.low_P_fluid.T, self.low_P_fluid.P))
                T = throat.therm.T(self.low_P_fluid.P, rho)
                v = throat.therm.a(T = T, P = self.low_P_fluid.P)
            else:
                raise NotImplementedError('Notional nozzle model not defined properly, ' + 
                                          "nn_T must be specified temperature or 'solve_energy'")
        fluid = copy.copy(throat)
        #print("velocity notional nozzle",v)
        fluid.update(rho = rho, P = self.low_P_fluid.P, v = v)
        # conserve mass to solve for effective diameter:
        orifice = Orifice(np.sqrt(self.orifice.mdot(throat)/(fluid.rho*fluid.v)*4/np.pi))
        #print ("orifice", orifice)
        #print ("=================================================")
        #print ("The source model is intended to extrapolate conditions from the leak plane where the"\
        #       "pressure is relatively high and the flow area is equal to the leak area to "\
        #       "an “equivalent source” where the pressure is atmospheric and the flow area is"\
        #       "somewhat larger than the leak area.")
        #print("Notional Nozzle Conditions are:") 
        #print ("fluid density = ", fluid.rho)
        #print ("Velocity = a= ", fluid.v)
        #print ("Pressure (= has to be P_atm) =",fluid.P)
        #print ("Temperature=", fluid.T)
        #print ("=================================================")
        #print ("From Notional Nozzle model orifice dimensions are =", orifice)
        #print ("=================================================")
        #print ("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
        #print ("At the exit of notional nozzle and inlet to zone 2")
        #print ("===========================================================")
        #print ("fluid=", fluid)
        #print ("orifice=", orifice)
        #print ("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
        return fluid, orifice    
