"""
Copyright 2015-2021 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights in this software.

You should have received a copy of the GNU General Public License along with HyRAM+.
If not, see https://www.gnu.org/licenses/.
"""

from __future__ import print_function, absolute_import, division

import copy
import warnings
import logging

import numpy as np
from scipy import integrate, optimize
from ._therm import CoolPropWrapper
#++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


log = logging.getLogger(__name__)


class Fluid:
    def __init__(self, T=None, P=None, rho=None, v=0.,
                 species='H2', phase=None, therm=None):
        '''
        class used to describe a fluid (usually a gas)
        two of four (T, P, rho, phase) are needed to fully define the fluid
        
        Parameters
        ----------
        therm : thermodynamic class
            a thermodynamic class that is used to relate state variables
        T : float
            temperature (K)
        P: float
            pressure (Pa)
        rho: float
            density (kg/m^3)
        v: float
            velocity (m/s)
        species: string
            species (either formula or name - see CoolProp documentation)
        phase: {None, 'gas', 'liquid'}
            either 'gas' or 'liquid' if fluid is at the satrated state.
        '''
        if therm is None:
            therm = CoolPropWrapper(species)

        if phase is not None:
            if T is not None and P is None and rho is None:
                rho, P = therm.rho_P(T, phase)
            elif P is not None and T is None and rho is None:
                rho, T = therm.rho_T(P, phase)
            elif rho is not None and T is None and P is None:
                P, T = therm.P_T(rho, phase)
            else:
                raise ValueError('Fluid not properly defined - too many or too few fluid initilization variables')
        elif T is not None and P is not None and rho is None:
            rho = therm.rho(T, P)
        elif rho is not None and P is not None and T is None:
            T = therm.T(P, rho)
        elif T is not None and rho is not None and P is None:
            P = therm.P(T, rho)
        else:
            raise ValueError('Fluid not properly defined - too many or too few fluid initilization variables')
        self.T, self.P, self.rho, self.phase = T, P, rho, therm.phase
        self.therm = therm
        self.v = v
        self.species = species

    def update(self, T=None, P=None, rho=None, v=None):
        if v != None:
            self.v = v
        if T != None and P != None:
            self.T = T
            self.rho = self.therm.rho(T, P)
            self.P = P
        elif T != None and rho != None:
            self.T = T
            self.rho = rho
            self.P = self.therm.P(T, rho)
        elif P != None and rho != None:
            self.T = self.therm.T(P, rho)
            self.rho = rho
            self.P = P
        elif v != None:
            self.v = v
        else:
            warnings.warn('No updates made.  Update not properly defined')

    def __repr__(self):
        return 'Gas\n%s\n  P = %.3f bar\n  T = %0.1f K\n  rho = %.3f kg/m^3)\n  v = %.1f m/s' % (
            30 * '-', self.P * 1e-5, self.T, self.rho, self.v)

class Orifice:
    def __init__(self, d, Cd=1.):
        '''
        class used to describe a circular orifice
        
        future versions may be expanded to give effective area for other shapes
        
        Parameters
        ----------
        d - orifice diameter (m)
        Cd - discharge coefficient to account for non-plug flow (always <=1, assumed to be 1 for plug flow)
        
        Contains
        --------
        d - diameter (m)
        Cd- discharge coefficient 
        A - effective area (m^2)
        '''
        self.d, self.Cd, self.A = d, Cd, np.pi / 4 * d ** 2

    def __repr__(self):
        return 'orifice\n%s\ndiameter = %.2f mm\ndischarge coefficient = %.2f' % (30 * '-', self.d * 1e3, self.Cd)

    def mdot(self, fluid):
        '''
        mass flow rate through orifice of a fluid object
        
        Parameters
        ----------
        rho - density (kg/m^3)
        v - velocity (m/s)
        
        Returns
        -------
        mdot - mass flow rate (kg/s)
        '''
        #print("mdot fluid rho=", fluid.rho)
        #print("mdot  fluid velocity=", fluid.v)
        #print("mdot  Area=", self.A)
        #print("mdot Cd=", self.Cd)
        #print("mass flow rate=", fluid.rho * fluid.v * self.A * self.Cd)
        return fluid.rho * fluid.v * self.A * self.Cd

    def flow(self, upstream_fluid, downstream_P=101325.):
        '''
        Returns the fluid in a flow restriction, for given upstream conditions 
        and downstream pressure.  Isentropic expansion.
        
        Parameters
        ----------
        upstream_fluid - upstream fluid with therm object, as well as P, T, rho, v
        
        Returns
        -------
        Fluid object containing T, P, rho, v at the throat (orifice)
        '''
        h0 = upstream_fluid.therm.PropsSI('H', T = upstream_fluid.T, D = upstream_fluid.rho)
        h0 += upstream_fluid.v**2/2
        if upstream_fluid.v > 0:
            s0 = upstream_fluid.therm.PropsSI('S', H = h0, D = np.round(upstream_fluid.rho, 12))
        else: #LH2 simulations were giving weird results when calculating entropy from enthalpy
            s0 = upstream_fluid.therm.PropsSI('S', D = upstream_fluid.rho, T = upstream_fluid.T)
            #s0 = PR_Cal_S_rhoT.find_S_rhoT(upstream_fluid.rho, upstream_fluid.T )
        
        fluid = copy.copy(upstream_fluid)
        a = upstream_fluid.therm.a(P = downstream_P, S = s0)
        #ht, rho = upstream_fluid.therm.PropsSI(['H', 'D'], P = downstream_P, S = s0)
        ht, rho = upstream_fluid.therm.PropsSI(['H', 'D'], P = downstream_P, S = s0)
        if h0 >= ht:
            if a >= np.sqrt(2 * (h0 - ht)):  # unchoked
                P = downstream_P
                fluid.update(rho=rho, P=P, v=np.sqrt(2 * (h0 - ht)))
                fluid._choked = False
                return fluid
        else:  # unable to calculate flow rate - enthalpy of upstream fluid greater than enthalpy at throat pressure
            fluid.update(rho=rho, P=downstream_P, v=np.nan)
            fluid._choked = None  # None rather than true/false may cause error - need to monitor
            return fluid

        def err_P_sonic(P):
            a = upstream_fluid.therm.a(P = P, S = s0)
            h = upstream_fluid.therm.PropsSI('H', P = P, S = s0)
            if 2 * (h0 + upstream_fluid.v ** 2 / 2. - h) > 0:
                v = np.sqrt(2 * (h0 + upstream_fluid.v ** 2 / 2. - h))
            else:
                v = 0
            return v - a

        try:
            P = optimize.brentq(err_P_sonic, upstream_fluid.P, downstream_P)
            if P <= downstream_P: # This shouldn't happen since there was a check above...
                P = downstream_P
                rho, T, ht = upstream_fluid.therm.PropsSI(['D', 'T', 'H'], P = P, S = s0)
                #T = 32.6
                #rho=1.21
                fluid.update(rho=rho, P=P, v=np.sqrt(2 * (h0 - ht)))
                #fluid.update(rho=rho, P=P, v=np.sqrt(2 * (h0 - ht)), T=T)
                fluid._choked = False
            else:
                a = upstream_fluid.therm.a(P = P, S = s0)
                rho = upstream_fluid.therm.PropsSI('D', P = P, S = s0)
                fluid.update(rho=rho, P=P, v=a)
                fluid._choked = True
                print ("flow is choked")
        except:
            rho, T, ht = upstream_fluid.therm.PropsSI(['D', 'T', 'H'], P = downstream_P, S = s0)
            fluid.update(rho=rho, P=downstream_P, v=np.sqrt(2 * (h0 - ht)))
            fluid._choked = False
            #print ("In exception, Need to check the conditions at code at line no 203 in _comps.py")
        #print("Conditions are choked at nozzle exit and thus we need to force v=a and find"\
        #      " the pressure > P_atm at the downstream; this higher P lead to form the Mach disk in this case")
        #print("We need to find the roots or value of P at throat which makes v-a=0, P in range [P_tank,P_atm] ")
        #print("==============================================================================================")
        #print("Choked Conditions are:")
        #print ("fluid density = ", fluid.rho)
        #print ("Velocity = a= ", fluid.v)
        #print ("Pressure (>P_atm) =",fluid.P)
        #rint ("Temperature=", fluid.T)
        #rint("==============================================================================================")
        #rint ("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
        #print ("Inlet to Notional Nozzle is")
        #print ("fluid at choked conditions=", fluid)
        #print ("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
        '''
        We model the isentropic expansion through the orifice in this section as 
        getting the choked conditions at the inlet of the orifice
        '''
        """
        def err_P_orifice_adiabatic(P, p_in, rho_in, T_in, m_in, d_in,alpha):  
            P2=P
            p1 = p_in
            rho1 = rho_in
            T1= T_in
            A = (np.pi/4)*(d_in**2)
            h1 = fluid.therm.PropsSI('H', P=p1, T=T1)
            rho2 = 1.0/((1/(rho_in*alpha)) - ((P-alpha*p_in)/((m_in/A)**2)))
            print (rho2)
            h2 = fluid.therm.PropsSI('H', P = P2, D=rho2)
            E_residual = (h2+0.5*(m_in/(A*rho2)**2)) - (h1+0.5*(m_in/(alpha*A*rho1)**2)) 
            #  print (E_residual)
            return E_residual
        def orifice_expansion_Adia(p_in, rho_in, v_in, T_in, P_oo, d_in, alpha):
            m_in = rho_in*(np.pi/4)*(d_in**2)*v_in
            A = (np.pi/4)*(d_in**2)
            P = optimize.brentq(lambda P: err_P_orifice_adiabatic(P, p_in, rho_in, T_in, m_in, d_in, alpha), p_in, P_oo)
            rho2 = 1.0/((1/(rho_in*alpha)) - ((P-alpha*p_in)/((m_in/A)**2)))
            #print (rho2)
            T2 = fluid.therm.PropsSI('T', P= P, D=rho2)
            #print (T2)
            T_exit_orifice = T2 
            rho_exit_orifice =  rho2
            V_exit_orifice = m_in/(rho2*(np.pi/4)*(d_in**2))
            P_exit_orifice = P
            return (P_exit_orifice, rho_exit_orifice, V_exit_orifice, T_exit_orifice)
        p_2, rho_2, v_2, T_2 = orifice_expansion_Adia(fluid.P, fluid.rho, fluid.v, fluid.T, 101325.0, 1/1000, 0.8 )# 0.6)
        #p_2, rho_2, v_2, T_2 = orifice_expansion(245357.06099688308, 1.6694545000680003-0.02,  498.10456292025265, 37.35167170692618, 101325.0)
        print ("Orifice fluid density = ", rho_2)
        print ("Orifice velocity", v_2)
        print ("Orifice pressure=",p_2)
        print ("Orifice Temperature=", T_2)
        print ("+++++++++++++++++++++++++++++++++++++++++++++++++++++")
        print ("===============Orifice model is on==================")
        #print ("===============Orifice model is off==================")
        print ("+++++++++++++++++++++++++++++++++++++++++++++++++++++")
        fluid.update(rho=rho_2, P=p_2, v=v_2, T=T_2)
        """
        return fluid

    def compute_steady_state_mass_flow(self, fluid, amb_pres=101325.):
        """
        Calculate mass flow rate based on given conditions.

        Parameters
        ----------
        fluid : Fluid
            Release fluid object

        amb_pres : float, optional
            Ambient fluid pressure (Pa).

        dis_coeff : float
            Discharge coefficient to account for non-plug flow (always <=1, assumed to be 1 for plug flow).

        Returns
        ----------
        mass_flow_rate : float
            Mass flow rate (kg/s) of steady release.

        """
        return self.mdot(self.flow(fluid, amb_pres))

class Source(object):
    """
    Used to describe a source (tank) that contains a fluid

    Attributes
    ----------
    mass : float
        mass of source (kg)

    """

    def __init__(self, V, fluid):
        '''
        Initializes source based on the volume and the fluid object in the source (tank)
        
        Parameters
        ----------
        V: float
            volume of source (tank) (m^3)
        fluid : Fluid
            fluid object in the source (tank)

        Returns
        -------
        source: object
            object containing .fluid (fluid obejct), .V (volume, m^3), and .m (mass (kg))
        '''
        self.fluid = fluid
        self.V = V
        self.m = self.mass = fluid.rho * V

    @classmethod
    def fromMass(cls, m, fluid):
        '''
        Initilization method based on the mass and the fluid object in the source (tank)
        
        Parameters
        ----------
        m: float
            mass of source (tank) (kg)
        fluid: object
            fluid object in the source (tank)
        
        Returns
        -------
        source: object
            object containing .fluid (fluid obejct), .V (volume, m^3), and .m (mass (kg))
        '''
        V = m / fluid.rho
        return cls(V, fluid)

    @classmethod
    def fromMass_Vol(cls, m, V, T=None, P=None, species='H2'):
        '''
        Initilization method based on the mass, volume, and either the temperature or pressure of the fluid 
        in the source (tank).
        
        Parameters
        ----------
        m: float
            mass of source (tank) (kg)
        V: float
            volume of source (tank) (m^3)
        therm: object
            thermodynamic class used to releate pressure, temperature and density
        T: float (optional)
            temperature (K)
        P: float (optional)
            pressure (Pa)
        
        Returns
        -------
        source: object
            object containing .fluid (fluid obejct), .V (volume, m^3), and .m (mass (kg)).
        returns none if eitehr underspecified (neither T or P given) or overspecified (both T and P given)
        '''
        rho = m / V
        if T is not None and P is None:
            fluid = Fluid(rho=rho, T=T, species=species)
        elif T is None and P is not None:
            fluid = Fluid(rho=rho, P=P, species=species)
        else:
            return None
        return cls(V, fluid)

    def mdot(self, orifice, downstream_P=101325.):
        '''returns the mass flow rate through an orifice, from the current tank conditions'''
        return orifice.compute_steady_state_mass_flow(self.fluid, downstream_P)

    def _blowdown_gov_eqns(self, t, ind_vars, Vol, orifice, heat_flux, ambient_P):
        '''governing equations for energy balance on a tank (https://doi.org/10.1016/j.ijhydene.2011.12.047)
        
        Parameters
        ----------
        t - time (s)
        ind_vars - array of mass (kg), internal energy (J/kg) in tank
        Vol - float, volume of tank (m^3)
        orifice - orifice object
        heat_flux - float, heat flow into tank (W)
        
        Returns
        -------
        [dm_dt, du_dt] = array of [d(mass)/dt (kg/s), d(internal energy)/dt (J/kg-s)]
                       = [-rho_throat*v_throat*A_throat, 1/m*(Q_in + mdot_out*(u - h_out))]
        '''
        therm = self.fluid.therm
        m, U = ind_vars
        m, U = float(m), float(U)
        rho = m / Vol
        T = therm.PropsSI('T', U = U, D = np.round(rho, 10))
        fluid = copy.copy(self.fluid)
        fluid.update(T=T, rho=rho)
        throat = orifice.flow(fluid, ambient_P)
        # h = therm.h(T = fluid.T, D = fluid.rho)
        h = therm.PropsSI('H', T=fluid.T, D=fluid.rho)
        dm_dt = -orifice.mdot(throat)
        du_dt = 1. / m * (heat_flux + (h - U) * dm_dt)
        return np.array([dm_dt, du_dt])
   
    def empty(self, orifice, ambient_P = 101325., 
              heat_flux = 0, nmax = 1000, 
              m_empty = 1e-6, p_empty_percent = .01):
        '''
        integrates the governing equations for an energy balance on a tank 
        
        Parameters
        ----------
        orifice - orifice object through which the source is emptying
        ambient_P - ambient pressure into which leak occurs (Pa)
        heat_flux - Heat flow (W) into tank.  Assumed to be 0 (adiabatic)
        nmax - maximum number of iterations
        m_empty - mass when considered empty (kg)
        p_empty_percent - percent of ambient pressure when considered empty
        
        Returns
        -------
        tuple of (mdot, fluid_list, t, solution_array) =
                 (list of mass flow rates (kg/s), list of fluid objects at each time step, 
                  array of times (s), 2D array of [mass, internal energy] at each time step)
        '''
        therm = self.fluid.therm
        m0 = self.m
        volume = self.V
        A_orifice = orifice.A * orifice.Cd
        T0, rho0, P = self.fluid.T, self.fluid.rho, self.fluid.P
        u0 = therm.PropsSI('U', T = T0, D = rho0)
        r = integrate.ode(self._blowdown_gov_eqns).set_integrator('dopri5')
        r.set_initial_value([m0, u0]).set_f_params(volume, orifice, heat_flux, ambient_P)
        throat = orifice.flow(self.fluid, ambient_P)
        mdot0 = orifice.mdot(throat)
        dt = m0 / mdot0
        times, fluid_list, mdot, sol = [], [], [], []

        def solout(t, y):
            if len(times) > 0:
                if times[-1] == t:
                    return
            rho = y[0] / volume
            T = therm.PropsSI('T', U = y[1], D = np.round(rho, 10))
            fluid = copy.copy(self.fluid)
            fluid.update(T=T, rho=rho)
            throat = orifice.flow(fluid, ambient_P)
            fluid_list.append(fluid)
            mdot.append(orifice.mdot(throat))
            times.append(t)
            sol.append([y[0], y[1]])

        r.set_solout(solout)
        nsteps = 0
        while (True):
            nsteps += 1
            try:
                r.integrate(r.t + dt)
            except:
                for i in range(100):
                    try:
                        # need to back up to last successful integration point
                        j = np.argmin(np.abs(np.array(times) - r.t))
                        times = times[:j + 1]
                        fluid_list = fluid_list[:j + 1]
                        mdot = mdot[:j + 1]
                        sol = sol[:j + 1]
                        dt /= 10
                        r.integrate(r.t + dt)
                        break
                    except:
                        print(i, 'unable to advance past time %.1f s with remaining mass of %.3f g, P = %.1f Pa' %
                              (r.t, r.y[0] * 1000, fluid_list[-1].P))
                        return mdot, fluid_list, times, np.array(sol).T
            if (not r.successful() or mdot[-1] < m_empty or
                    fluid_list[-1].P < (1 + p_empty_percent / 100) * ambient_P or
                    nsteps > nmax):
                break
        return mdot, fluid_list, times, np.array(sol).T


class Enclosure:
    '''
    Enclosure used in the overpressure modeling
    '''

    def __init__(self, H, A, H_release, ceiling_vent, floor_vent, Xwall=np.inf):
        '''
        Describes the enclosure
        
        Parameters
        ----------
        H : encosure height (m)
        A : area of floor and ceiling (m^2) 
        H_release : height of release (m)
        ceiling_vent : vent class containing vent information for ceiling vent
        floor_vent : vent class containing vent information for floor vent
        Xwall : perpendicular from jet to wall (m)
        '''
        self.H, self.A, self.ceiling_vent, self.floor_vent = H, A, ceiling_vent, floor_vent
        self.H_release, self.Xwall = H_release, Xwall
        self.V = H * A


class Vent:
    '''
    Vent used in overpressure modeling
    '''

    def __init__(self, A, H, Cd=1, vol_flow_rate=0):
        '''
        Describes the vent
        
        Parameters
        ----------
        A : vent cross-sectional area (m^2)
        H : vent height from floor (m)
        Cd: discharge coefficient of vent
        vol_flow_rate: volumetric flow rate through the vent (m^3/s)
        '''
        self.A, self.H, self.Cd, self.vol_flow_rate = A, H, Cd, vol_flow_rate
        self.Qw = Cd * vol_flow_rate / np.sqrt(2)  # See Lowesmith et al IJHE 2009
