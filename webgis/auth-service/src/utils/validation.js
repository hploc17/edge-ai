import { z } from "zod";

export const registerSchema = z.object({
  name: z.string().trim().min(2, "Tên phải có tối thiểu 2 ký tự"),
  email: z.string().trim().email("Email không đúng định dạng"),
  password: z.string().min(8, "Mật khẩu phải có tối thiểu 8 ký tự"),
});

export const loginSchema = z.object({
  email: z.string().trim().email("Email không đúng định dạng"),
  password: z.string().min(1, "Vui lòng nhập mật khẩu"),
});

export const updateProfileSchema = z
  .object({
    name: z.string().trim().min(2, "Tên phải có tối thiểu 2 ký tự").optional(),
    email: z.string().trim().email("Email không đúng định dạng").optional(),
    currentPassword: z.string().optional(),
    newPassword: z.string().min(8, "Mật khẩu mới phải có tối thiểu 8 ký tự").optional(),
  })
  .refine(
    (data) => {
      // Nếu có newPassword thì bắt buộc có currentPassword
      if (data.newPassword && !data.currentPassword) {
        return false;
      }
      return true;
    },
    {
      message: "Vui lòng nhập mật khẩu hiện tại để đổi mật khẩu mới",
      path: ["currentPassword"],
    }
  );

export const createManagerSchema = z.object({
  name: z.string().trim().min(2, "Tên phải có tối thiểu 2 ký tự"),
  email: z.string().trim().email("Email không đúng định dạng"),
  password: z.string().min(8, "Mật khẩu phải có tối thiểu 8 ký tự"),
});

export const updateManagerSchema = z.object({
  name: z.string().trim().min(2, "Tên phải có tối thiểu 2 ký tự").optional(),
  email: z.string().trim().email("Email không đúng định dạng").optional(),
  password: z.string().min(8, "Mật khẩu mới phải có tối thiểu 8 ký tự").optional(),
});
