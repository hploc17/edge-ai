export type Role = "ADMIN" | "MANAGER" | "USER";

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
  createdAt?: string;
  updatedAt?: string;
}

export interface AuthResponse {
  token: string;
  user: User;
}

export interface ManagerPagination {
  total: number;
  page: number;
  limit: number;
  totalPages: number;
}

export interface ManagerListResponse {
  managers: User[];
  pagination: ManagerPagination;
}
