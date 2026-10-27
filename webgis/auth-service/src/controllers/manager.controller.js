import { ManagerService } from "../services/manager.service.js";
import { asyncHandler } from "../utils/asyncHandler.js";
import { createManagerSchema, updateManagerSchema } from "../utils/validation.js";

export class ManagerController {
  static list = asyncHandler(async (req, res) => {
    const { page, limit, search } = req.query;
    const result = await ManagerService.listManagers({ page, limit, search });

    res.status(200).json({
      success: true,
      data: result,
    });
  });

  static create = asyncHandler(async (req, res) => {
    const validatedData = createManagerSchema.parse(req.body);
    const newManager = await ManagerService.createManager(validatedData);

    res.status(201).json({
      success: true,
      message: "Tạo tài khoản MANAGER thành công",
      data: { manager: newManager },
    });
  });

  static update = asyncHandler(async (req, res) => {
    const { id } = req.params;
    const validatedData = updateManagerSchema.parse(req.body);
    const updated = await ManagerService.updateManager(id, validatedData);

    res.status(200).json({
      success: true,
      message: "Cập nhật tài khoản MANAGER thành công",
      data: { manager: updated },
    });
  });

  static delete = asyncHandler(async (req, res) => {
    const { id } = req.params;
    const result = await ManagerService.deleteManager(req.user.userId, id);

    res.status(200).json({
      success: true,
      message: result.message,
    });
  });
}
