"use client";

import React, { useContext, useState } from "react";
import { motion } from "framer-motion";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { AuthContext } from "../components/contexts/AuthContext";
import { RegisterPayload } from "../api/auth/signup";
import { RouterContext } from "../components/contexts/RouterContext";

const defaultRegisterForm: RegisterPayload = {
  email: "",
  password: "",
  display_name: "",
};

const AuthPage: React.FC = () => {
  const { isAuthenticated, loading, register, login } = useContext(AuthContext);
  const { changePage } = useContext(RouterContext);

  const [mode, setMode] = useState<"login" | "register">("login");
  const [registerForm, setRegisterForm] =
    useState<RegisterPayload>(defaultRegisterForm);
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [submitting, setSubmitting] = useState(false);

  const handleRegisterSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const success = await register({
        ...registerForm,
      });
      if (success) {
        setMode("login");
        setRegisterForm(defaultRegisterForm);
        changePage("profile", {}, true);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const success = await login(loginForm);
      if (success) {
        changePage("chat");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const renderAuthForms = () => (
    <Tabs
      value={mode}
      onValueChange={(value) => setMode(value as "login" | "register")}
    >
      <TabsList className="w-full">
        <TabsTrigger value="login" className="flex-1">
          Đăng nhập
        </TabsTrigger>
        <TabsTrigger value="register" className="flex-1">
          Đăng ký
        </TabsTrigger>
      </TabsList>
      <TabsContent value="login">
        <Card className="border-secondary/10 bg-background_alt">
          {/* <CardHeader>
            <CardTitle>Sign in</CardTitle>
            <CardDescription>
              Access your MealAgent workspace
            </CardDescription>
          </CardHeader> */}
          <CardContent>
            <form className="space-y-4 mt-4" onSubmit={handleLoginSubmit}>
              <div>
                <Label htmlFor="login-email" className="text-sm">Email</Label>
                <Input
                  id="login-email"
                  type="email"
                  required
                  value={loginForm.email}
                  onChange={(e) =>
                    setLoginForm({ ...loginForm, email: e.target.value })
                  }
                  placeholder="email@example.com"
                  className="h-12 rounded-lg px-3 shadow-sm"
                />
              </div>
              <div>
                <Label htmlFor="login-password" className="text-sm">Mật khẩu</Label>
                <Input
                  id="login-password"
                  type="password"
                  required
                  value={loginForm.password}
                  onChange={(e) =>
                    setLoginForm({ ...loginForm, password: e.target.value })
                  }
                  placeholder="••••••••"
                  className="h-12 rounded-lg px-3 shadow-sm"
                />
              </div>
              <Button type="submit" className="w-full h-12 rounded-lg shadow-md" disabled={submitting}>
                {submitting ? "Đang đăng nhập..." : "Đăng nhập"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="register">
        <Card className="border-secondary/10 bg-background_alt">
          {/* <CardHeader>
            <CardTitle>Create account</CardTitle>
            <CardDescription>
              Set up your credentials to save preferences
            </CardDescription>
          </CardHeader> */}
          <CardContent>
            <form className="space-y-4 mt-4" onSubmit={handleRegisterSubmit}>
              <div>
                <Label htmlFor="register-name" className="text-sm">Tên hiển thị</Label>
                <Input
                  id="register-name"
                  required
                  value={registerForm.display_name}
                  onChange={(e) =>
                    setRegisterForm({
                      ...registerForm,
                      display_name: e.target.value,
                    })
                  }
                  placeholder="Nguyễn Văn A"
                  className="h-12 rounded-lg px-3 shadow-sm"
                />
              </div>
              <div>
                <Label htmlFor="register-email" className="text-sm">Email</Label>
                <Input
                  id="register-email"
                  type="email"
                  required
                  value={registerForm.email}
                  onChange={(e) =>
                    setRegisterForm({ ...registerForm, email: e.target.value })
                  }
                  placeholder="email@example.com"
                  className="h-12 rounded-lg px-3 shadow-sm"
                />
              </div>
              <div>
                <Label htmlFor="register-password" className="text-sm">Mật khẩu</Label>
                <Input
                  id="register-password"
                  type="password"
                  required
                  value={registerForm.password}
                  onChange={(e) =>
                    setRegisterForm({
                      ...registerForm,
                      password: e.target.value,
                    })
                  }
                  placeholder="Tối thiểu 8 ký tự"
                  className="h-12 rounded-lg px-3 shadow-sm"
                />
              </div>
              <Button type="submit" className="w-full h-12 rounded-lg shadow-md" disabled={submitting}>
                {submitting ? "Đang tạo tài khoản..." : "Tạo tài khoản"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  );

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="flex flex-1 w-full max-w-5xl mx-auto py-12 px-4"
    >
      <div className="w-full max-w-xl mx-auto">
        {/* Auth forms (centered) */}
        <div className="w-full">
          <div className="text-center mb-6 lg:mb-8">
            <h1 className="text-3xl md:text-4xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary to-accent mb-2">
              {isAuthenticated
                ? "Đang chuyển hướng đến trang chính..."
                : "Chào mừng đến với MealAgent"}
            </h1>
            <p className="text-secondary mt-1">
              {isAuthenticated
                ? "Vui lòng chờ trong khi chúng tôi tải không gian làm việc của bạn."
                : "Tạo tài khoản hoặc đăng nhập để cá nhân hóa kế hoạch bữa ăn của bạn."}
            </p>
          </div>

          {loading ? (
            <div className="w-full flex justify-center py-12">
              <p className="text-secondary">Đang tải tài khoản...</p>
            </div>
          ) : (
            <div className="bg-background_alt border border-secondary/10 rounded-2xl shadow-xl p-6">
              {renderAuthForms()}
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
};

export default AuthPage;

