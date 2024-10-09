"""
Copyright 2015-2021 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights in this software.

You should have received a copy of the GNU General Public License along with HyRAM+.
If not, see https://www.gnu.org/licenses/.
"""

from __future__ import print_function, absolute_import, division

import copy
import warnings

import matplotlib.pyplot as plt
import numpy as np
from scipy import integrate, optimize
import scipy.constants as const
from scipy.interpolate import interp1d
from ._nn import NotionalNozzle

from scipy import optimize
########################################################################
#TODO: untested for alternate fuels
########################################################################
from ..utilities.custom_warnings import PhysicsWarning
import importlib.util
import sys
sys.path.append( "C:\\Users\\sainid\\OneDrive - The University of Melbourne\\Documents 1\\Documents_Backup\\HyRAM_New_Approach\\HyRAM\\hyram-master\\hyram-master\\src\\hyram\\hyram\\phys\\")
from realGasEoSFunc_New import find_T_rhoP_Mixture, derivative_T_rhoP_Mixture, derivative_T_Y_Mixture, find_rho_PT_Mixture

########################################################################################################################
class DevelopingFlow:
    def __init__(self, fluid, orifice, ambient ,mdot = None,
                 theta0 = 0, x0 = 0., y0 = 0.,
                 lam  = 1.16, betaA = 0.28, 
                 nn_conserve_momentum = True, nn_T = 'solve_energy', 
                 T_establish_min = -1, suppressWarnings = False):
        '''
        Engineering correlations to calculate the Gaussian profile boundary conditions for
        the flow through an orifice lam=1.16 (actual in the code)
        '''
        S0 = 0 # S always starts at 0. x and y may start somewhere else.
        Y0 = 1.0 # pure fluid
        
        # Orifice flow
        self.orifice = orifice
        #print ("suppressWarnings",suppressWarnings) ## dsaini
        self.fluid_orifice = self._orifice_flow(fluid, orifice, ambient, mdot, suppressWarnings) # plug node at orifice exit
        #print ("suppressWarnings",suppressWarnings) ## dsaini
       # print ("VERY IMPORTANT Choked conditions T",self.fluid_orifice.T)
        self.d0 = orifice.d
        self.T_orf = self.fluid_orifice.T
        self.orifice_node = PlugNode(orifice.d, self.fluid_orifice.v, self.fluid_orifice.rho,
                                     1, self.fluid_orifice.T, theta0, x0, y0, S0)
        print (suppressWarnings) ## dsaini
        # Underexpanded jet (if needed: gets fluid to atmospheric pressure)
        self.fluid_exp, self.orifice_exp = self._expand(orifice, ambient, nn_T, nn_conserve_momentum)
 
        # Initial entrainment and heating (if needed: warms fluid to good T for thermodynamics)
        # dsaini: Use this for modelling air entrainment as well as NO Zone 2
        # _dev_plug_energy_loss
        self.expanded_plug_node = self._dev_plug(self.fluid_exp, self.orifice_exp, ambient, Y0, theta0, x0, y0, S0, 
                                                T_establish_min, betaA)

        # Develop into established Gaussian profile from plug flow
        #self.initial_node = self.expanded_plug_node.establish(ambient, self.fluid_exp, lam)
        self.initial_node = self.expanded_plug_node.establish(ambient, self.fluid_exp, lam, betaA)
        #self.initial_node = self.expanded_plug_node.establish_new(ambient, self.fluid_exp, lam)
        
        
    def _orifice_flow(self, fluid, orifice, ambient, mdot, suppressWarnings):
        '''
        flow thorugh the orifice
        '''
        #print ("=============================================================")
        #print ("Here in the orifice_flow update conditions")
        fluid_out = orifice.flow(fluid, ambient.P)
        if fluid_out._choked and mdot is not None:
            if not suppressWarnings:
                warnings.warn('Fluid over-specified. Using choked flow calculation of mass flow.', category=PhysicsWarning)
        elif not fluid_out._choked and mdot is None:
            if not suppressWarnings:
                warnings.warn('Fluid unchoked. Verification or specification of mass flow rate suggested.',
                              category=PhysicsWarning)
        elif fluid_out._choked and mdot is None:
            #print ("Pass in this routine without any chnages")
            #print ("=============================================================")
            pass
        else:
            fluid_out = copy.copy(fluid)
            fluid_out.update(T = fluid.T, P = ambient.P)
            fluid_out.update(v = mdot/(fluid_out.rho*orifice.A))
            #print (" 2 Here in the orifice_flow update conditions")
        return fluid_out
    
    def _expand(self, orifice, ambient, nn_T, nn_conserve_momentum):
        '''
        expands an underexpanded jet, if needed
        '''
        if self.fluid_orifice.P > ambient.P: # use notional nozzle model
            print("In notional nozzle model")
            nn = NotionalNozzle(self.fluid_orifice, orifice, ambient)
            g, o = nn.calculate(nn_T, nn_conserve_momentum)
        else:
            g, o = self.fluid_orifice, orifice
        return g, o

    def _dev_plug(self, fluid, orifice, ambient, Y0, theta0, x0, y0, S0, 
                  T_establish_min, betaA):
        '''
        zone of initial entrainment and heating (if needed)
        conservation of energy and mass while air being entrained
        '''
        T_establish_min=-1
        if fluid.T > T_establish_min:
            plug_node = PlugNode(orifice.d, fluid.v, fluid.rho, Y0, fluid.T, theta0, x0, y0, S0)
        else:
            air_out = copy.copy(ambient) # air conditions kept same as ambient
            air_out.update(T = T_establish_min, P = air_out.P) # Update the temperaturev of air
            fluid_out = copy.copy(fluid)
            fluid_out.update(T = T_establish_min, P = fluid_out.P)
            mdot_in = orifice.mdot(fluid)
            h_in = fluid.therm.PropsSI('H', T = fluid.T, D = fluid.rho) + fluid.v**2/2. # dsaini (checked)
            h_air_in = ambient.therm.PropsSI('H', T = ambient.T, P = ambient.P)#dsaini (checked)
            h_air_out = air_out.therm.PropsSI('H', T = air_out.T, D = air_out.rho) #dsaini (checked)
            print ("h_air_out",h_air_out, "at Temperature", air_out.T, "and density", air_out.rho)
            h_fluid_out = fluid_out.therm.PropsSI('H',T = fluid_out.T, D = fluid_out.rho) #dsaini (checked)
            print ("h_fluid_out",h_fluid_out, "at Temperature", fluid_out.T, "and density", fluid_out.rho)
            def errH(Y):
                h_out = (1-Y)*h_air_out + Y*h_fluid_out
                rho_out = 1./((1.-Y)/air_out.rho + Y/fluid_out.rho)
                mdot_out = mdot_in + (1.-Y)/Y*mdot_in # assumes mdot_in is pure #last term gives m_air
                v_out = fluid.v*mdot_in/mdot_out # Momentum balance equation assumes air velocity is very small 
                h_out = h_out + v_out**2/2. # total enthalpy
                return mdot_in*h_in + (mdot_out - mdot_in)*h_air_in - mdot_out*h_out # Residual of energy equation
            Y = optimize.brentq(errH, 1.e-6, 1.) # This Gives the value of Y for which Residual of energy is zero
            rho_out = 1./((1.-Y)/air_out.rho + Y/fluid_out.rho)
            mdot_out = mdot_in + (1.-Y)/Y*mdot_in
            v_out = fluid.v*mdot_in/mdot_out
            betaA_near = (betaA*2*(rho_out/fluid_out.rho)**0.5)/((rho_out/fluid_out.rho)+1)
            E = betaA*np.sqrt(orifice.mdot(fluid)*fluid.v/ambient.rho) 
            S_out = (1-Y)*(mdot_out - mdot_in)/E/ambient.rho
            d_out = np.sqrt(mdot_out/(rho_out*v_out)*4/np.pi)
            plug_node = PlugNode(d_out, v_out, rho_out, Y, fluid_out.T, theta0, 
                                 x0 + S_out*np.cos(theta0), y0 + S_out*np.sin(theta0), S0 + S_out)
        return plug_node
    
class PlugNode:
    def __init__(self, d, v, rho, Y, T, theta, x = 0, y = 0, S = 0):
        '''Plug flow node
        
        Parameters
        ----------
        d: float, diameter (m)
        v: float, velocity (m/s)
        rho: float, density (kg/m^3)
        Y: float, mass fraction fuel
        theta: float, release angle from horizontal (rad)
        x: float, x position (m),
        y: float, y position (m),
        S: float, distance along streamline (m)
        '''
        
        self.d, self.v, self.rho, self.Y = d, v, rho, Y
        self.theta, self.x, self.y, self.S = theta, x, y, S
        self.T = T
    
    def Froude(self, rho_amb):
        '''Froude number'''
        return self.v/np.sqrt(const.g*self.d*abs(rho_amb - self.rho)/self.rho) #ESH - 7/23/20 - added abs to work with negatively buoyant jets
    
    def establish(self, ambient, fluid, lam, betaA):
        '''
        returns the gaussian node after flow establishment
        '''
        V_clE = self.v
        BE = self.d/np.sqrt(2*(2*lam**2+1)/(lam**2*self.rho/ambient.rho + lam**2 + 1))
        Y_clE = self.Y*(lam**2+1.)/(2.*lam**2)
        h_amb, cp_ambient = ambient.therm.PropsSI(['H', 'C'], T = ambient.T, P = ambient.P) #Pure Air

        cp_gas = fluid.therm.PropsSI('C', T = (self.T + ambient.T)/2., P = ambient.P)
        #cp_gas = fluid.therm.PropsSI('C', T = self.T, P = ambient.P) #Pure H2
        MW_clE =  1.0 / (Y_clE / fluid.therm.MW + (1.0 - Y_clE) / ambient.therm.MW) 
        h_amb = ambient.T*cp_ambient #Pure Air
        cp_s3 = cp_gas # Pure H2
        T_s3 = self.T
        h_s3 = cp_s3 * T_s3 #Pure H2
        h_clE = h_amb + (lam**2+1.)/(2.*lam**2)*(h_s3 - h_amb) #Mixture Corr
        cp_clE = Y_clE * cp_gas + (1.0 - Y_clE) * cp_ambient #Mixture 
        T_clE = (h_clE / cp_clE) #Mixture
        Y_clE_mole = (Y_clE*ambient.therm.MW)/(fluid.therm.MW + Y_clE*ambient.therm.MW - Y_clE*fluid.therm.MW)
        #rho_clE = PR_Cal_rho_PT_Mixture.find_rho_PT_Mixture(ambient.P, T_clE, Y_clE_mole)
        #print ("rho_clE old one", rho_clE)
        rho_clE = find_rho_PT_Mixture(ambient.P, T_clE, Y_clE_mole)
        print ("rho_clE new one", rho_clE)
        #rho_clE = PengRobinsonH2N2().find_rho_PT_Mixture(ambient.P, T_clE, Y_clE_mole)
        #rho_clE = (ambient.P*MW_clE/(const.R*T_clE)) #Mixture
        #######################################################################################
        # Note: correlation below is for Fr**2 > 40, which is pretty much always true for these 
        # gases - could add Froude number correlation if desired
        #######################################################################################
        SE = 6.2*self.d
        xE = self.x + SE*np.cos(self.theta)
        yE = self.y + SE*np.sin(self.theta)
        SE = self.S + SE
        thetaE = self.theta
        return GaussianNode(BE, V_clE, rho_clE, Y_clE, thetaE, xE, yE, SE)

class GaussianNode:
    def __init__(self, B, v_cl, rho_cl, Y_cl, theta, x = 0, y = 0, S = 0):
        '''
        Describes the properties of a node 
        
        Parameters
        ----------
        B: float
            Gaussian halfwidth (m)
        v_cl : float
            velocity at centerline (m/s)
        rho_cl : float
            density at centerline (kg/m^3)
        Y_cl : float
            mass fraction at centerline (kg/kg)
        theta: float
            angle of jet (rad, 0 is horizontal)
        x: float
            horizontal postion of node (m)
        y: float
            vertical postion of node (m)
        S : float (optional)
            length along jet(m)
        '''
        self.B, self.v_cl, self.rho_cl, self.Y_cl = B, v_cl, rho_cl, Y_cl
        self.S, self.theta, self.x, self.y = S, theta, x, y
    
    @property
    def conditions(self):
        return np.array([self.v_cl, self.B, self.rho_cl, self.Y_cl, self.theta, self.x, self.y])    

    def entrainment(self, Emom, rho_amb, alpha_buoy, alpha):
        FrL = self.v_cl**2*self.rho_cl/(const.g*self.B*abs(rho_amb-self.rho_cl)) # ESH: added absolute value 07/23/20 - for negatively buoyant jets, this was a negative number - might need justification
        E_buoy = alpha_buoy/FrL*(2*const.pi*self.v_cl*self.B)*np.sin(self.theta)  # m**2/s
        E = Emom + E_buoy
        #E = Emom #+ Emom
        alphatest = E/(2*const.pi*self.v_cl*self.B)
        if alphatest > alpha:
            E = alpha*2*const.pi*self.B*self.v_cl
        return E        


class Jet:
    def __init__(self, fluid, orifice, ambient, solver_model, mdot = None,
                 theta0 = 0, x0 = 0., y0 = 0.,
                 lam  = 1.16, betaA = 0.28,
                 nn_conserve_momentum = True, nn_T = 'solve_energy', 
                 T_establish_min = 80, 
                 Ymin = 7e-4, dS = None, Smax = np.inf, 
                 max_steps = 5000, tol = 1e-8,
                 alpha = 0.082, Yamb = 0., numB = 5, numpts = 500,
                 suppressWarnings = False, verbose = True):
        '''
        Class for solving for a 2D jet. 
        If fluid pressure is <= 2 x ambient pressure, use subsonic initilization (specify mdot).
               
        Parameters
        ----------
        fluid: fluid object
            the fluid (fluid) that is being released
        orifice: orifice object
            the release
        ambient: fluid object
            the fluid into which the release occurs
        mdot: float, optional defaults to None
            mass flow rate (kg/s). Only used if flow is not choked.
        theta0 : float, optional defaults to horizontal
            angle of release, radians (0 is horizontal, pi/2 is vertical)
        x0: float, optional
            horizontal starting location (m)
        y0: float, optional
            vertical starting location (m)     
        lam : float, optional
            Relative spreading ratio of concentration to velocity (dsaini)
        betaA : float, optional
            proportionality constant for air entrainment (see Li et al IJHE 2015)(dsaini)
        nn_conserve_momentum: boolean, optional
            whether notional nozzle model should conserve mass and momentum, or mass only,
            together with nn_T determines which notional nozzle model to use (see below)
        nn_T: string, optional
            either 'solve_energy', 'Tthroat' or specified temperature (stagnation temperature) 
            with nn_conserve_momentum leads to one of the following notinoal nozzle models:
            YuceilOtugen - conserve_momentum = True, T = 'solve_energy'
            EwanMoodie - conserve_momentum = False, T = 'Tthroat'
            Birch - conserve_momentum = False, T = T0
            Birch2 - conserve_momentum = True, T = T0
            Molkov - conserve_momentum = False, T = 'solve_energy'
        T_establish_min: float, optional (dsaini)
            minimum temperature (K) at the zone of flow establishment, if specified, will implement the 
            zone of initial entrainment and heating if tempearture after notional nozzle model is lower
        Ymin: float, optional
            minimum mass fraction to integrate to (default is about 1 mol%)
        dS: float, optional
            integrator step size, if None, defaults to 500 diameters, solver adds steps in high gradient areas
        Smax: float, optional
            maximum limit of integration, integrator will stop when it reaches Ymin or Smax
        max_steps: float, optional
            maximum steps for integrator
        tol: float, optional
            relative and absolute tolerance for integrator
        alpha: float, optional (dsaini)
            empirical buoyancy induced entrainment constant
        Yamb: float, optional
            mass fraction of fluid in the ambient air
        numB: float, optional
            maximum number of halfwidths (B) considered to be infinity - for integration in energy equations
        numpts: int, optional
            maximum number of points in energy integration (from 0 to numB)
        suppressWarnings: boolean, optional
            whether to display warnings about fluid being under-/over-specified in DevelopingFlow (dsaini) object
        verbose: boolean, optional
            whether to include print statements about the model actions
        There are up to 4 engineering models that give initial conditions to an 
        integral model:
        1) flow through the orifice - choked if pressure above critical pressure, assumed
           to be plug flow at volumetric flow rate if not
        2) if choked, underexpanded (notional nozzle)
        3) if choked and < 60K, initial entrainment and heating
        4) flow establishment

        Properties
        ----------
        S : ndarray of floats
            distance (m) along jet?
        '''
        lam = 1.16
        betaA = 0.28
        self.verbose = verbose
        #=====================================================================#      
        self.developing_flow = DevelopingFlow(fluid, orifice, ambient, mdot,
                                              theta0 = theta0, x0 = x0, y0 = y0,
#                                              lam  = lam, betaA = betaA,
                                              lam =1.16 , betaA =  0.28,
                                              nn_conserve_momentum = nn_conserve_momentum, nn_T = nn_T, 
                                              T_establish_min = T_establish_min, suppressWarnings = suppressWarnings
                                              )
        self.initial_node = self.developing_flow.initial_node
        # Developing flow includes Zone 0, 1, 2 and 
        #=====================================================================#
        # Set up some entrainment parameters:
        Fr = self.developing_flow.expanded_plug_node.Froude(ambient.rho)
        self.Fr = Fr
        if Fr < 268:
            self._alpha_buoy = 17.313-0.11665*Fr+(2.0771e-4)*Fr**2 
        else:
            self._alpha_buoy = 0.97
        expanded_plug_node = self.developing_flow.expanded_plug_node
        self._Emom = betaA*np.sqrt(const.pi/4.0*expanded_plug_node.d**2*
                                   expanded_plug_node.rho*expanded_plug_node.v**2/ambient.rho)
        # some other objects and parameters that I don't want to keep recalculating
        # note: method of calculating heat capacity and enthalpy makes a significant difference in terms
        # of trajectory and density in the calculations...
        self.lam, self.fluid, self.ambient, self.lamT = lam, fluid, ambient, lam
        self.solver_model = solver_model
        #####################################################################################################
        # TODO: account for variations in heat capacity as a function of temperature - used when getting rid of
        #       heat capacity in _gov_eqns
        MW_air, MW_fluid = ambient.therm.MW, fluid.therm.MW
        MW_cl0 = MW_air*MW_fluid/(self.initial_node.Y_cl*(MW_air - MW_fluid) + MW_fluid)
        T_cl0 = (ambient.P*MW_cl0/(const.R*self.initial_node.rho_cl)) #
        # TODO: determine if _Cp_fluid should be at ambient T, or T_cl0
        self._Cp_fluid = self.fluid.therm.PropsSI('C', T = ambient.T, P = ambient.P)
        self._Cp_air, self._h_amb0 = ambient.therm.PropsSI(['C', 'H'], T = ambient.T, P = ambient.P)

        
        # Integrate in the zone of established flow
        self.solve(Ymin, dS, Smax, max_steps, tol, alpha, Yamb, numB, numpts)
    
    def solve(self, Ymin = 7e-4, dS = None, Smax = np.inf, 
              max_steps = 5000, tol = 1e-8,
              alpha = 0.082, Yamb = 0., numB = 5, numpts = 500):
        '''
        solves (integrates) the model equations from the initial node out to limit
        '''
        if self.verbose:
            print('integrating... ', end='')

        if dS is None and Smax == np.inf:
            dS = 500*self.developing_flow.expanded_plug_node.d # somewhat arbitrary - solver will add points anyway 
                                        # may integrate past Ymin 
        elif dS is None:
            dS = Smax

        r = integrate.ode(self._govEqns).set_f_params(alpha, Yamb, numB, numpts)
        r.set_integrator('dopri5', atol = tol, rtol = tol)
        #r.set_integrator('dop853', atol = tol, rtol = tol)
        
        T, Y = [], []
        def solout(t, y):
            T.append(t)
            Y.append(np.array(y))
        r.set_solout(solout)
        r.set_initial_value(self.initial_node.conditions, self.initial_node.S)
        
        i = 0
        while r.successful() and r.y[3] > Ymin and i < max_steps and r.t < Smax:
            r.integrate(r.t + dS)
            i += 1
            
        Y = np.array(Y)
        
        for key, val in zip(['V_cl', 'B', 'rho_cl', 'Y_cl', 'theta', 'x', 'y'], Y.T):
            self.__dict__[key] = val
        self.__dict__['S'] = np.array(T)

        MW_fluid, MW_air = self.fluid.therm.MW, self.ambient.therm.MW
        MW_cl  = MW_air*MW_fluid/(self.Y_cl*(MW_air-MW_fluid) + MW_fluid)
        self.X_cl = self.Y_cl*MW_cl/MW_fluid
        self.T_cl = (self.ambient.P*MW_cl/(const.R*self.rho_cl))#
        if self.verbose:
            print('done.')

        return self
    
    def _govEqns(self, S, ind_vars, alpha = 0.082, Yamb = 0., numB = 5, numpts = 500):
        '''
        Governing equations for a plume, written in terms of d/dS of (V_cl, B, rho_cl, Y_cl, 
        theta, x, and y).
        
        A matrix solution to the continuity, x-momentum, y-momentum, species, and energy 
        equations solves for d/dS of the dependent variables V_cl, B, rho_cl, Y_cl,  and Theta.  
        Numerically integrated to infinity = numB * B(S) using numpts discrete points.
        '''
        # break independent variables out of ind_vars, then put them into node_in
        
        [V_cl, B, rho_cl, Y_cl, theta, x, y] = ind_vars
        node_in = GaussianNode(B, V_cl, rho_cl, Y_cl, theta, S = S)
        
        # pull some parameters out of objects so their definition isn't so long
        rho_amb, MW_air, MW_fluid = self.ambient.rho, self.ambient.therm.MW, self.fluid.therm.MW
        T_amb = self.ambient.T
        lam = self.lam
        lam_T = self.lamT
        Pamb = self.ambient.P
        h_amb0, Cp_fluid, Cp_air = self._h_amb0, self._Cp_fluid, self._Cp_air
        h_amb0 = Cp_air * self.ambient.T
        E = node_in.entrainment(self._Emom, rho_amb, self._alpha_buoy, alpha = alpha)
        # some stuff needed to integrate to infinity (numB*B):
        r = np.append(np.array([0]), np.logspace(-5, np.log10(numB*B), numpts))
        zero = np.zeros_like(r)
        V       = V_cl*np.exp(-(r**2)/(B**2))
        dVdS = np.array([V/V_cl,                                                 #d/dS(V_cl)
                         2*V*r**2/B**3,                                          #d/dS(B)
                         zero,                                                   #d/dS(rho_cl) 
                         zero,                                                   #d/dS(Y_cl)
                         zero])                                                  #d/dS(theta)
        rho     = ((rho_cl - rho_amb)*np.exp(-(r**2)/((lam*B)**2))+rho_amb)
        Y       = Y_cl*rho_cl/rho*np.exp(-r**2/(lam*B)**2)
        MW      = MW_air*MW_fluid/(Y*(MW_air - MW_fluid) + MW_fluid)
        MW_cl      = MW_air*MW_fluid/(Y_cl*(MW_air - MW_fluid) + MW_fluid)
        Cp      = Y*(Cp_fluid - Cp_air) + Cp_air # Old One
        MW      = MW_air*MW_fluid/(Y*(MW_air - MW_fluid) + MW_fluid)
        dYdS = np.array([zero,                                                        #d/dS(V_cl)
                         (2*Y**2*rho_amb*r**2*np.exp(r**2/(lam*B)**2)/
                         (lam**2*B**3*Y_cl*rho_cl)),                                  #d/dS(B)
                         Y**2*rho_amb*(np.exp(r**2/(lam*B)**2)-1)/(Y_cl*rho_cl**2),   #d/dS(rho_cl)
                         Y/Y_cl,                                                      #d/dS(Y_cl)
                         zero]) 
        drhodS  = np.array([zero,                                                     #d/dS(V_cl)
                             2*r**2*(rho_cl-rho_amb)/np.exp(r**2/(lam*B)**2),         #d/dS(B)
                             (lam**2*B**3)/np.exp(r**2/(lam*B)**2),                   #d/dS(rho_cl)
                             zero,                                                    #d/dS(Y_cl)
                             zero                                                     #d/dS(theta)
                             ])*1./(lam**2*B**3)
        dMWdS   = (MW*(MW_air - MW_fluid)/(MW_fluid*(Y-1) - MW_air*Y))*dYdS
        Cp      = Y*(Cp_fluid - Cp_air) + Cp_air # Old One
        dCpdS   = (Cp_fluid - Cp_air)*dYdS
        ###################################################################################################################
        if self.solver_model == 'Model2':
            X_cl = Y_cl*MW_cl/MW_fluid
            T_cl = find_T_rhoP_Mixture(rho_cl, Pamb, X_cl)
            dTdrho = derivative_T_rhoP_Mixture(rho_cl, Pamb, X_cl)
            dTdY = derivative_T_Y_Mixture(rho_cl, Pamb, X_cl)
            T = (T_cl-T_amb)*np.exp(-(r**2)/((lam_T*B)**2)) + T_amb
            dTdS = np.array([zero,                                                                               #d/dS(V_cl)
                             (T_cl-T_amb)*np.exp(-r**2/(lam_T*B)**2)*(2.0/B**3)*(r/lam_T)**2,                    #d/dS(B)
                             np.exp(-r**2/(lam_T*B)**2)*dTdrho,                                                  #d/dS(rho_cl)
                             np.exp(-r**2/(lam_T*B)**2)*dTdY,                                                    #d/dS(Y_cl)
                             zero]) 
            drhohdS = (rho*Cp*dTdS + rho*T*dCpdS + Cp*T*drhodS)
            rhoh = rho*Cp*T
        else: #HW model
            rhoh    = Pamb/const.R*MW*Cp
            drhohdS = Pamb/const.R*(MW*dCpdS + Cp*dMWdS)
        #################################################################################################################
        ##
        ######################################################################################################################
        # governing equations:
        LHScont = np.array([(lam**2*rho_cl + rho_amb)*B**2,                        #d/dS(V_cl)
                            2*(lam**2*rho_cl + rho_amb)*B*V_cl,                    #d/dS(B)
                            lam**2*B**2*V_cl,                                      #d/dS(rho_cl)
                            0.,                                                    #d/dS(Y_cl)
                            0.])*const.pi/(lam**2 + 1)                             #d/dS(theta)
        RHScont = rho_amb*E
        
        LHSxmom = np.array([(2*lam**2*rho_cl+rho_amb)*B**2*V_cl*np.cos(theta),     #d/dS(V_cl)
                            (2*lam**2*rho_cl+rho_amb)*B*V_cl**2*np.cos(theta),     #d/dS(B)
                            lam**2*B**2*V_cl**2*np.cos(theta),                     #d/dS(rho_cl)
                            0.,                                                    #d/dS(Y_cl)
                            -(2*lam**2*rho_cl+rho_amb)*(B*V_cl)**2*np.sin(theta)/2 #d/dS(theta)
                            ])*const.pi/(2*lam**2+1)        
        RHSxmom = 0.
        
        LHSymom = np.array([(2*lam**2*rho_cl+rho_amb)*B**2*V_cl*np.sin(theta),     #d/dS(V_cl)
                            (2*lam**2*rho_cl+rho_amb)*B*V_cl**2*np.sin(theta),     #d/dS(B)
                            lam**2*B**2*V_cl**2*np.sin(theta),                     #d/dS(rho_cl)
                            0.,                                                    #d/dS(Y_cl)
                            (2*lam**2*rho_cl+rho_amb)*(B*V_cl)**2*np.cos(theta)/2  #d/dS(theta)
                            ])*const.pi/(2*lam**2+1)                                 
        RHSymom = -const.pi*lam**2*const.g*(rho_cl - rho_amb)*B**2
        
        LHSspec = np.array([B*Y_cl*rho_cl,                                         #d/dS(V_cl)
                            2*V_cl*Y_cl*rho_cl,                                    #d/dS(B)
                            B*V_cl*Y_cl,                                           #d/dS(rho_cl)
                            B*V_cl*rho_cl,                                         #d/dS(Y_cl)
                            0.,                                                    #d/dS(theta)
                            ])*const.pi*lam**2*B/(lam**2 + 1)                
        RHSspec = Yamb*RHScont
        
        
        LHSener = 2*const.pi*integrate.trapz(V*drhohdS*r + rhoh*dVdS*r, r)
        LHSener += [const.pi/(6*lam**2 + 2)*(3*lam**2*rho_cl+rho_amb)*B**2*V_cl**2,   #d/dS(V_cl)
                    const.pi/(9*lam**2 + 3)*(3*lam**2*rho_cl+rho_amb)*V_cl**3*B ,     #d/dS(B)
                    const.pi/(6*lam**2 + 2)*lam**2*B**2*V_cl**3  ,                    #d/dS(rho_cl)
                    0. ,                                                              #d/dS(Y_cl)
                    0.]                                                               #d/dS(theta)
        
        RHSener = h_amb0*RHScont #
        
        LHS = np.array([LHScont,
                        LHSxmom,
                        LHSymom,
                        LHSspec,
                        LHSener
                        ])
        RHS = np.array([RHScont,
                        RHSxmom,
                        RHSymom,
                        RHSspec,
                        RHSener])
        
        dz = np.append(np.linalg.solve(LHS,RHS), np.array([np.cos(theta), np.sin(theta)]), axis = 0)
        return dz
    
    def reshape(self, enclosure, showPlot = False):
        '''
        reshapes the plume to turn upwards, should it hit the enclosure wall, 
        and crops it so it stops at the ceiling
        '''
        if np.any(self.x > enclosure.Xwall):
            iwall = np.argmax(self.x > enclosure.Xwall)
            for k in ['S', 'rho_cl', 'V_cl', 'Y_cl', 'B', 'theta', 'y', 'x']:
                self.__dict__[k] = np.append(np.append(self.__dict__[k][:iwall],
                                                       np.interp(enclosure.Xwall, self.x, self.__dict__[k])),
                                             self.__dict__[k][iwall:])
            self.y[iwall+1:] = self.y[iwall] + self.S[iwall+1:] - self.S[iwall]
            self.x[iwall:] = enclosure.Xwall
            self.theta[iwall:] = np.pi/2
        if np.any(self.y > enclosure.H):
            iceil = np.argmax(self.y > enclosure.H)
            for k in ['S', 'rho_cl', 'V_cl', 'Y_cl', 'B', 'theta', 'x', 'y']:
                np.append(self.__dict__[k][:iceil],
                          np.interp(enclosure.H, self.y, self.__dict__[k]))
        if showPlot == True:
            plt.plot(self.x,self.y)
        return self

    def m_flammable(self, X_lean = 0.04, X_rich = 0.75, Hmax = np.inf):
        '''
        calculates the amount of mass in the plume that is within the flammability limits
        
        Parameters
        ----------
        plume: plume class
          class of plume results
        X_lean: float
            mole fraction lower limit
        X_rich: float
            mole fraction upper limit
        Hmax: float
            maximum height for integration
        
        Outputs
        -------
        mass: float
          flammable mass in plume, up to height H (kg)
        '''
        from scipy import integrate
        MW_fluid = self.fluid.therm.MW
        MW_air = self.ambient.therm.MW
        Ylean  = X_lean*MW_fluid/(X_lean*MW_fluid+(1.-X_lean)*MW_air)
        Yrich  = X_rich*MW_fluid/(X_rich*MW_fluid+(1.-X_rich)*MW_air)

        # Trim the plume down to below Hmax:
        S = np.copy(self.S); Y_cl = np.copy(self.Y_cl)
        B = np.copy(self.B); rho_cl = np.copy(self.rho_cl)
        if np.all(self.y > Hmax) or np.all(self.Y_cl < Ylean) or np.all(self.Y_cl > Yrich): # no flammable mass 
            return 0
        elif np.any(self.y > Hmax): # trim arrays to Hmax
            S = np.append(S[np.argwhere(self.y < Hmax)].T[0], np.interp(Hmax, self.y, S))
            Y_cl = np.append(Y_cl[np.argwhere(self.y < Hmax)].T[0], np.interp(Hmax, self.y, Y_cl))
            B = np.append(B[np.argwhere(self.y < Hmax)].T[0], np.interp(Hmax, self.y, B))
            rho_cl = np.append(rho_cl[np.argwhere(self.y < Hmax)].T[0], np.interp(Hmax, self.y, rho_cl))
     
        def rhoY(r, i):
            'mass fraction and density at radius: r, for plume at node: i'
            rho = (rho_cl[i]-self.ambient.rho)*np.exp(-r**2/(self.lam*B[i]**2))+self.ambient.rho
            Y = rho_cl[i]*Y_cl[i]*np.exp(-r**2/(self.lam*B[i])**2)/rho
            return rho, Y
        
        # radius of flammable concentration at each node:
        r_lean = np.array([0 if Y_cl[i] < Ylean else 
                           optimize.brentq(lambda r: rhoY(r, i)[1] - Ylean, 0, 100*B[i])
                           for i in range(len(S))])
        r_rich = np.array([0 if Y_cl[i] < Yrich else 
                           optimize.brentq(lambda r: rhoY(r, i)[1] - Yrich, 0, 100*B[i])
                           for i in range(len(S))])
        # integrate to find the mass/length at each node
        mass = np.array([integrate.quad(lambda r: np.prod(rhoY(r, i))*2*const.pi*r, 
                                        r_r, r_l)[0] for i, r_r, r_l in zip(range(len(S)), r_rich, r_lean)])
        # integrate to find the total mass
        return integrate.trapz(mass, S)
    
    
    @property
    def _contourdata(self):
        """

        Returns
        -------
        x : ndarray
            horizontal positions along jet (m)
        y : ndarray
            vertical positions along jet (m)
        X : ndarray
            mole fractions
        Y : ndarray
            mass fractions
        v : ndarray
            velocities
        T : ndarray
            temperatures
        """
        iS = np.arange(len(self.S))
        T_amb = self.ambient.T
        # Calculates logspaced points around 0 out to np.log10(3*np.max(self.B))
        # poshalf[::-1] just notation for reversing a numpy array
        poshalf = np.logspace(-5, np.log10(3*np.max(self.B)))
        r = np.concatenate((-1.0 * poshalf[::-1], [0], poshalf))
        
        r, iS = np.meshgrid(r, iS)
        B = self.B[iS]
        rho_cl = self.rho_cl[iS]
        Y_cl = self.Y_cl[iS]
        V_cl = self.V_cl[iS] 
        lam_T = self.lamT                   
        rho_amb, Tamb, Pamb = self.ambient.rho, self.ambient.T, self.ambient.P
        MW_fluid, MW_air = self.fluid.therm.MW, self.ambient.therm.MW
        solver_model = self.solver_model
        if solver_model=='Model2':
            MW_cl  = MW_air*MW_fluid/(Y_cl*(MW_air-MW_fluid) + MW_fluid)
            rho = rho_amb + (rho_cl - rho_amb)*np.exp(-r**2/self.lam**2/B**2)
            Y   = Y_cl*rho_cl*np.exp(-(r**2)/((self.lam*B)**2))/rho
            MW  = MW_air*MW_fluid/(Y*(MW_air-MW_fluid) + MW_fluid)
        ############################################################################
            X = Y*MW/MW_fluid
            T = np.zeros((len(X[:,0]),len(X[0,:])))
            for i in range(len(X[:,0])):
               for j in range(len(X[0,:])):
                   T[i,j] = find_T_rhoP_Mixture(rho[i,j], Pamb, X[i,j])
        else:
            rho = rho_amb + (rho_cl - rho_amb)*np.exp(-r**2/self.lam**2/B**2)
            Y   = Y_cl*rho_cl*np.exp(-(r**2)/((self.lam*B)**2))/rho
            MW  = MW_air*MW_fluid/(Y*(MW_air-MW_fluid) + MW_fluid)
            T = (Pamb*MW/(const.R*rho))
        ##############################################################################
        X = Y*MW/MW_fluid
        v = V_cl*np.exp(-(r**2)/(B**2))
        x = self.x[iS] + r*np.sin(self.theta[iS])
        y = self.y[iS] - r*np.cos(self.theta[iS])
        return x, y, X, Y, v, T, rho, B
    
   
        
    
    def _radial_profile(self, distance, ind_var = 'Y', nB = 3):
        '''
        returns radial profile at a certain distance along the jet
        Parameters
        ----------
        distance: float
            distance along jet to plot profile
        ind_var: string
            independent variable to plot, either mass fraction ('Y'), mole fraction ('X') or velocity ('v')
        nB: int
            number of halfwidths to plot

        Returns
        -------
        [r, ind_var]: radial profile of independent variable from -nB*B to nB*B
        '''
        B = np.interp(distance, self.S, self.B)
        rho_cl = np.interp(distance, self.S, self.rho_cl)
        Y_cl = np.interp(distance, self.S, self.Y_cl)
        V_cl = np.interp(distance, self.S, self.V_cl)

        r = np.logspace(-5, np.log10(nB*B))
        r = np.concatenate((-1*r[::-1], [0], r))

        rho_amb, Tamb, Pamb = self.ambient.rho, self.ambient.T, self.ambient.P
        MW_fluid, MW_air = self.fluid.therm.MW, self.ambient.therm.MW

        rho = rho_amb + (rho_cl - rho_amb)*np.exp(-r**2/self.lam**2/B**2)
        Y   = Y_cl*rho_cl*np.exp(-(r**2)/((self.lam*B)**2))/rho
        MW  = MW_air*MW_fluid/(Y*(MW_air-MW_fluid) + MW_fluid)

        X = Y*MW/MW_fluid
        v = V_cl*np.exp(-(r**2)/(B**2))
        T = Pamb*MW/(const.R*rho)
        if ind_var == 'Y':
            return [r, Y]
        if ind_var == 'X':
            return [r, X]
        if ind_var == 'v':
            return [r, v]
        if ind_var == 'T':
            return [r, T]

    def get_contour_data(self):
        return self._contourdata

    def plot_moleFrac_Contour(self, mark=None, mcolors = 'w', xlims = None,
                              ylims = None, xlab = 'x (m)', ylab = 'y (m)', 
                              plot_title = None, vmin = 0, vmax = 0.1, 
                              addColorBar = True, aspect = 1, fig_params=None,
                              subplots_params=None, ax = None, fig = None, contlvls = False):
        '''
        makes mole fraction contour plot
        
        Parameters
        ----------
        mark: list or None, optional
            levels to draw contour lines (mole fractions, or None if None desired)
        mcolors: color or list of colors, optional
            colors of marked contour leves
        xlims: tuple, optional
            tuple of (xmin, xmax) for contour plot
        ylims: tuple, optional
            tuple of (ymin, ymax) for contour plot
        vmin: float, optional
            minimum mole fraction for contour plot
        vmax: float, optional
            maximum mole fraction for contour plot
        addColorBar: boolean, optional
            whether to add a colorbar to the plot
        aspect: float, optional
            aspect ratio of plot
        fig_params: dict or None, optional
            dictionary of figure parameters (e.g. figsize)
        subplots_params: dict or None, optional
            dictionary of subplots_adjust parameters (e.g. top)
        ax: optional
            axes on which to make the plot
        '''

        # Initialize missing params
        if mark is None:
            mark = [0.04]
        if subplots_params is None:
            subplots_params = {}
        if fig_params is None:
            fig_params = {}
        # Make figure and axis if not specified
        if ax is None and fig is None:
            fig, ax = plt.subplots(**fig_params)
            plt.subplots_adjust(**subplots_params)
        elif ax is None and fig is not None:
            ax = fig.subplots(**fig_params)
            plt.subplots_adjust(**subplots_params)
        
        # Get background color for contour
        ax.set_facecolor(plt.cm.get_cmap()(0)) #old matplotlib: ax.set_axis_bgcolor
        
        # Get contour data to plot
        x, y, X, __, __, __, __, __ = self._contourdata
        
        # Plot contour data
        if np.amax(X) > vmax and np.amin(X) < vmin:
            ExtStr = 'both'
        elif np.amax(X) > vmax and np.amin(X) >= vmin:
            ExtStr = 'max'
        elif np.amax(X) <= vmax and np.amin(X) < vmin:
            ExtStr = 'min'
        else:
            ExtStr = 'neither'
        if contlvls:
            contourstep = 0.01
            contourlevels = np.arange(vmin, vmax + contourstep, contourstep)
            cp = ax.contourf(x, y, X, contourlevels, extend = ExtStr,alpha=0.5)
        else:
            contourstep = 0.001
            contourlevels = np.arange(vmin, vmax + contourstep, contourstep)
            cp = ax.contourf(x, y, X, contourlevels, extend = ExtStr)
        
        # Add specific contours if desired
        if mark is not None:
            ax.contour(x, y, X, levels = mark, colors = mcolors, linewidths = 1.5)
            LabelStr = 'White contour{} at {}'.format({False:' is', True:'s \n are'}[len(mark)>1],mark[0])
            for i in range(1, len(mark)-1):
                LabelStr += ', {}'.format(mark[i])
            if len(mark) > 1:
                LabelStr += ' and {}'.format(mark[-1])
            ax.text(0.5, 0.9, LabelStr, color = 'white',
                    horizontalalignment = 'center', 
                    verticalalignment = 'center', 
                    transform = ax.transAxes)
        
        # Change axis limits if specified
        if xlims is not None:
            ax.set_xlim(*xlims)
        if ylims is not None:
            ax.set_ylim(*ylims)
        
        # Add colorbar if desired
        if addColorBar:
            #cb = plt.colorbar(cp,orientation="horizontal")
            #cb.set_label('mole fraction', rotation = 0, va = 'bottom',labelpad=+20.0)
            cb = plt.colorbar(cp)
            cb.set_label('mole fraction', rotation = -90, va = 'bottom')
        
        # Set axis labels
        ax.set_xlabel(xlab)
        ax.set_ylabel(ylab)
        
        # Set aspect ratio if specified
        if aspect is not None:
            ax.set_aspect(aspect)
        
        # Set plot title if specified
        if plot_title is not None:
            ax.set_title(plot_title)
        
        return fig
    
    def plot_massFrac_Contour(self, mark = None, mcolors = 'w', 
                              xlims = None, ylims = None,
                              xlab = 'x (m)', ylab = 'y (m)',
                              vmin = 0, vmax = 1, levels = 100,
                              addColorBar = True, aspect = 1, 
                              fig_params=None, subplots_params=None, ax = None):
        '''
        makes mole fraction contour plot
        
        Parameters
        ----------
        mark: list, optional
            levels to draw contour lines (mass fractions, or None if None desired)
        mcolors: color or list of colors, optional
            colors of marked contour leves
        xlims: tuple, optional
            tuple of (xmin, xmax) for contour plot
        ylims: tuple, optional
            tuple of (ymin, ymax) for contour plot
        vmin: float, optional
            minimum mole fraction for contour plot
        vmax: float, optional
            maximum mole fraction for contour plot
        levels: int, optional
            number of contours levels to draw
        addColorBar: boolean, optional
            whether to add a colorbar to the plot
        aspect: float, optional
            aspect ratio of plot
        fig_params: dict or None, optional
            dictionary of figure parameters (e.g. figsize)
        subplots_params: dict or None, optional
            dictionary of subplots_adjust parameters (e.g. top)
        ax: optional
            axes on which to make the plot
        '''
        if subplots_params is None:
            subplots_params = {}
        if fig_params is None:
            fig_params = {}
        if ax is None:
            fig, ax = plt.subplots(**fig_params)
            plt.subplots_adjust(**subplots_params)

        ax.set_facecolor(plt.cm.get_cmap()(0))
        x, y, __, Y, __, __ = self._contourdata
        cp = ax.contourf(x, y, Y, levels, vmin = vmin, vmax = vmax)
        if mark is not None:
            ax.contour(x, y, Y, levels = mark, colors = mcolors, linewidths = 1.5)
        
        if xlims is not None:
            ax.set_xlim(*xlims)
        if ylims is not None:
            ax.set_ylim(*ylims)
        
        if addColorBar:
            cb = plt.colorbar(cp)
            cb.set_label('Hydrogen Mass Fraction', rotation = -90, va = 'bottom')
        ax.set_xlabel(xlab)
        ax.set_ylabel(ylab)
        if aspect is not None:
            ax.set_aspect(aspect)
        return fig
    
    def plot_velocity_Contour(self, mark = None, mcolors = 'w', 
                              xlims = None, ylims = None,
                              xlab = 'x (m)', ylab = 'y (m)',
                              levels = 100,
                              addColorBar = True, aspect = 1, 
                              fig_params=None, subplots_params=None, ax=None, **kwargs):
        '''
        makes mole fraction contour plot
        
        Parameters
        ----------
        mark: list, optional
            levels to draw contour lines (mass fractions, or None if None desired)
        mcolors: color or list of colors, optional
            colors of marked contour leves
        xlims: tuple, optional
            tuple of (xmin, xmax) for contour plot
        ylims: tuple, optional
            tuple of (ymin, ymax) for contour plot
        vmin: float, optional
            minimum mole fraction for contour plot
        vmax: float, optional
            maximum mole fraction for contour plot
        levels: int, optional
            number of contours levels to draw
        addColorBar: boolean, optional
            whether to add a colorbar to the plot
        aspect: float, optional
            aspect ratio of plot
        fig_params: dict or None, optional
            dictionary of figure parameters (e.g. figsize)
        subplots_params: dict or None, optional
            dictionary of subplots_adjust parameters (e.g. top)
        ax: optional
            axes on which to make the plot
        '''
        if subplots_params is None:
            subplots_params = {}
        if fig_params is None:
            fig_params = {}
        if ax is None:
            fig, ax = plt.subplots(**fig_params)
            plt.subplots_adjust(**subplots_params)
        ax.set_facecolor(plt.cm.get_cmap()(0))
        x, y, __, __, v, __ = self._contourdata
        cp = ax.contourf(x, y, v, levels, **kwargs)
        if mark is not None:
            cp2 = ax.contour(x, y, v, levels = mark, colors = mcolors, lw = 1.5, **kwargs)
        
        if xlims is not None:
            ax.set_xlim(*xlims)
        if ylims is not None:
            ax.set_ylim(*ylims)
        
        if addColorBar:
            cb = plt.colorbar(cp)
            cb.set_label('Hydrogen Velocity', rotation = -90, va = 'bottom')
        ax.set_xlabel(xlab); ax.set_ylabel(ylab)
        if aspect is not None:
            ax.set_aspect(aspect)
        return plt.gcf()

    def get_mass_flow_rate(self):
        """
        Calculates mass flow rate for the jet plume

        Returns
        ----------
        mass_flow_rate : float
            Mass flow rate (kg/s) of steady release.
        """
        return self.developing_flow.orifice.compute_steady_state_mass_flow(self.fluid, self.ambient.P)
