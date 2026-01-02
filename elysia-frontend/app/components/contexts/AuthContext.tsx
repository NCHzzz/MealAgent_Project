"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  AuthSuccessResponse,
  LoginPayload,
  RegisterPayload,
  ProfileUpdatePayload,
  fetchProfile,
  loginUser,
  logoutUser,
  registerUser,
  updateProfile,
  UserProfileResponse,
} from "@/app/api/auth/signup";
import { ToastContext } from "./ToastContext";

type AuthUser = {
  user_id: string;
  email: string;
  display_name?: string;
  token: string;
  role?: string;
};

type AuthContextValue = {
  authUser: AuthUser | null;
  profile: UserProfileResponse | null;
  isAuthenticated: boolean;
  loading: boolean;
  register: (payload: RegisterPayload) => Promise<boolean>;
  login: (payload: LoginPayload) => Promise<boolean>;
  logout: () => void;
  saveProfile: (payload: ProfileUpdatePayload) => Promise<boolean>;
  refreshProfile: () => Promise<void>;
  activeUserId: string | null;
  isAdmin: boolean;
};

const STORAGE_KEY = "elysia_auth_user";

export const AuthContext = createContext<AuthContextValue>({
  authUser: null,
  profile: null,
  isAuthenticated: false,
  loading: true,
  register: async () => false,
  login: async () => false,
  logout: () => {},
  saveProfile: async () => false,
  refreshProfile: async () => {},
  activeUserId: null,
  isAdmin: false,
});

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const { showErrorToast, showSuccessToast } = useContext(ToastContext);
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [profile, setProfile] = useState<UserProfileResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const cached = window.localStorage.getItem(STORAGE_KEY);
    if (cached) {
      try {
        const parsed = JSON.parse(cached) as AuthUser;
        setAuthUser(parsed);
      } catch (err) {
        console.error(err);
        window.localStorage.removeItem(STORAGE_KEY);
        setLoading(false);
      }
    } else {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!authUser?.token) {
      setProfile(null);
      if (loading) {
        setLoading(false);
      }
      return;
    }
    // Fetch profile when authUser token is available
    const loadProfile = async () => {
      setLoading(true);
      try {
        const resp = await fetchProfile(authUser.token);
        if (!resp.error) {
          setProfile(resp.profile || null);
        } else {
          showErrorToast("Profile error", resp.error);
        }
      } catch (err) {
        console.error("Error fetching profile:", err);
        showErrorToast("Profile error", "Failed to load profile data.");
      } finally {
        setLoading(false);
      }
    };
    void loadProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authUser?.token]);

  const persistUser = (user: AuthUser | null) => {
    if (typeof window === "undefined") return;
    if (user) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  };

  const handleAuthSuccess = useCallback(
    (resp: AuthSuccessResponse) => {
      const user: AuthUser = {
        user_id: resp.user_id,
        email: resp.email,
        display_name: resp.display_name,
        token: resp.token,
        role: resp.role,
      };
      setAuthUser(user);
      setProfile(resp.profile || null);
      persistUser(user);
      return user;
    },
    []
  );

  const registerHandler = useCallback(
    async (payload: RegisterPayload) => {
      const resp = await registerUser(payload);
      if ("user_id" in resp && resp.error === "") {
        handleAuthSuccess(resp as AuthSuccessResponse);
        showSuccessToast("Account created", "Your MealAgent profile is ready.");
        return true;
      }
      showErrorToast("Registration failed", resp.error || "Unable to register.");
      return false;
    },
    [handleAuthSuccess, showErrorToast, showSuccessToast]
  );

  const loginHandler = useCallback(
    async (payload: LoginPayload) => {
      const resp = await loginUser(payload);
      if ("user_id" in resp && resp.error === "") {
        handleAuthSuccess(resp as AuthSuccessResponse);
        showSuccessToast("Welcome back!", "You are now signed in.");
        return true;
      }
      showErrorToast("Login failed", resp.error || "Unable to login.");
      return false;
    },
    [handleAuthSuccess, showErrorToast, showSuccessToast]
  );

  const logoutHandler = useCallback(() => {
    if (authUser?.token) {
      void logoutUser(authUser.token);
    }
    setAuthUser(null);
    setProfile(null);
    persistUser(null);
    showSuccessToast("Signed out", "You have been signed out.");
  }, [authUser?.token, showSuccessToast]);

  const refreshProfile = useCallback(async () => {
    if (!authUser?.token) return;
    const resp = await fetchProfile(authUser.token);
    if (resp.error) {
      showErrorToast("Profile error", resp.error);
      return;
    }
    setProfile(resp.profile || null);
  }, [authUser?.token, showErrorToast]);

  const saveProfile = useCallback(
    async (payload: ProfileUpdatePayload) => {
      if (!authUser?.token) {
        showErrorToast("Not authenticated", "Please login to update profile.");
        return false;
      }
      const resp = await updateProfile(authUser.token, payload);
      if (resp.error) {
        showErrorToast("Failed to update profile", resp.error);
        return false;
      }
      // Update profile with response (includes recalculated nutritional targets)
      setProfile(resp.profile || null);
      
      // Refresh profile to ensure we have the latest calculated values
      // This ensures tdee_kcal, protein_g, fat_g, carb_g are up-to-date
      try {
        await refreshProfile();
      } catch (err) {
        // If refresh fails, use the response profile (should have calculated values)
        console.warn("Failed to refresh profile after update:", err);
      }
      
      showSuccessToast("Profile updated", "Your preferences and nutritional targets have been recalculated.");
      return true;
    },
    [authUser?.token, showErrorToast, showSuccessToast, refreshProfile]
  );

  const value = useMemo(
    () => ({
      authUser,
      profile,
      isAuthenticated: Boolean(authUser?.token),
      loading,
      register: registerHandler,
      login: loginHandler,
      logout: logoutHandler,
      saveProfile,
      refreshProfile,
      activeUserId: authUser?.user_id || null,
      isAdmin: authUser?.role === "admin" || profile?.role === "admin",
    }),
    [
      authUser,
      profile,
      loading,
      registerHandler,
      loginHandler,
      logoutHandler,
      saveProfile,
      refreshProfile,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

