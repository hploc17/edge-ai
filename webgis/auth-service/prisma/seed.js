import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";
import dotenv from "dotenv";

dotenv.config();

const prisma = new PrismaClient();

async function main() {
  const adminEmail = (process.env.ADMIN_EMAIL || "admin@traffic.gis.local").toLowerCase().trim();
  const adminPassword = process.env.ADMIN_PASSWORD || "AdminSecurePass@2026";
  const adminName = process.env.ADMIN_NAME || "System Administrator";

  console.log(`[SEED] Kiểm tra tài khoản Admin mặc định: ${adminEmail}...`);

  const existingAdmin = await prisma.user.findUnique({
    where: { email: adminEmail },
  });

  if (existingAdmin) {
    console.log(`[SEED] Tài khoản Admin (${adminEmail}) đã tồn tại trong CSDL. Bỏ qua.`);
    return;
  }

  const salt = await bcrypt.genSalt(10);
  const hashedPassword = await bcrypt.hash(adminPassword, salt);

  const admin = await prisma.user.create({
    data: {
      name: adminName,
      email: adminEmail,
      password: hashedPassword,
      role: "ADMIN",
    },
  });

  console.log(`[SEED] ✅ Đã tạo tài khoản ADMIN thành công:`);
  console.log(`       - ID: ${admin.id}`);
  console.log(`       - Email: ${admin.email}`);
  console.log(`       - Role: ${admin.role}`);
}

main()
  .catch((e) => {
    console.error("[SEED ERROR] Lỗi khi tạo tài khoản Admin seed:", e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
