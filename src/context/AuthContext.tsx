import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import {
  ApiUser,
  getCurrentUserApi,
  loginApi,
  logoutApi,
  registerApi,
  updateProfileApi,
} from '../services/api';

export interface User {
  id: string;
  name: string;
  email: string;
  createdAt: string;
}

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, pass: string, rememberMe?: boolean) => Promise<boolean>;
  register: (name: string, email: string, pass: string) => Promise<boolean>;
  updateProfile: (name: string, email: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const fromApiUser = (user: ApiUser): User => ({
  id: user.id,
  name: user.displayName,
  email: user.email,
  createdAt: user.createdAt,
});

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    try {
      const current = await getCurrentUserApi();
      setUser(current ? fromApiUser(current.user) : null);
    } catch {
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshUser();
  }, [refreshUser]);

  const login = async (email: string, pass: string) => {
    const result = await loginApi(email, pass);
    setUser(fromApiUser(result.user));
    return true;
  };

  const register = async (name: string, email: string, pass: string) => {
    const result = await registerApi(name, email, pass);
    setUser(fromApiUser(result.user));
    return true;
  };

  const updateProfile = async (name: string, email: string) => {
    const updated = await updateProfileApi({ displayName: name, email });
    setUser(fromApiUser(updated));
  };

  const logout = async () => {
    try {
      await logoutApi();
    } finally {
      setUser(null);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        register,
        updateProfile,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};
