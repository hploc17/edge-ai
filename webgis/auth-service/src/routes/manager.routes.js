import { Router } from "express";
import { ManagerController } from "../controllers/manager.controller.js";
import { authenticate, authorizeRoles, ADMIN_ONLY, requireFreshDbUser } from "../middlewares/auth.js";

const router = Router();

// Mọi route quản lý Manager đều bắt buộc:
// 1. authenticate (có Bearer JWT hợp lệ)
// 2. authorizeRoles(ADMIN_ONLY) (role trong token phải là ADMIN)
// 3. requireFreshDbUser (đối chiếu lại CSDL để đảm bảo Admin còn tồn tại và không bị hạ quyền)
router.use(authenticate, authorizeRoles(ADMIN_ONLY), requireFreshDbUser);

// GET /api/admin/managers - Danh sách có phân trang & tìm kiếm
router.get("/", ManagerController.list);

// POST /api/admin/managers - Tạo tài khoản MANAGER mới
router.post("/", ManagerController.create);

// PUT /api/admin/managers/:id - Cập nhật thông tin / reset mật khẩu MANAGER
router.put("/:id", ManagerController.update);

// DELETE /api/admin/managers/:id - Xóa tài khoản MANAGER
router.delete("/:id", ManagerController.delete);

export default router;
