import { Router } from "express";
import { AuthController } from "../controllers/auth.controller.js";
import { authenticate } from "../middlewares/auth.js";
import { loginRateLimiter, registerRateLimiter } from "../middlewares/rateLimiter.js";

const router = Router();

// POST /api/auth/register (Public, kèm Rate-limit)
router.post("/register", registerRateLimiter, AuthController.register);

// POST /api/auth/login (Public, kèm Rate-limit chống Brute-force)
router.post("/login", loginRateLimiter, AuthController.login);

// GET /api/auth/me (Yêu cầu đăng nhập - mọi role)
router.get("/me", authenticate, AuthController.getMe);

// PATCH /api/auth/me (Yêu cầu đăng nhập - mọi role tự sửa thông tin cá nhân)
router.patch("/me", authenticate, AuthController.updateMe);

export default router;
