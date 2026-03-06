import {
  apiDelete,
  apiGet,
  apiPost,
  apiPut,
} from "@/common/services/api";
import type {
  FeeStructure,
  StudentFee,
  CreateStructureInput,
  UpdateStructureInput,
  RecordPaymentInput,
} from "../types";

export const financeService = {
  // Fee structures
  getStructures: async (params?: {
    academic_year_id?: string;
    class_id?: string;
  }) => {
    let url = "/api/finance/structures";
    if (params) {
      const q = new URLSearchParams();
      if (params.academic_year_id) q.append("academic_year_id", params.academic_year_id);
      if (params.class_id) q.append("class_id", params.class_id);
      const qs = q.toString();
      if (qs) url += `?${qs}`;
    }
    const res = await apiGet<{ fee_structures: FeeStructure[] }>(url);
    return res.fee_structures ?? [];
  },

  getStructure: async (id: string) => {
    const res = await apiGet<FeeStructure>(`/api/finance/structures/${id}`);
    return res;
  },

  getAvailableClassesForStructure: async (
    academicYearId: string,
    excludeStructureId?: string | null
  ) => {
    let url = `/api/finance/structures/available-classes?academic_year_id=${academicYearId}`;
    if (excludeStructureId) {
      url += `&exclude_structure_id=${excludeStructureId}`;
    }
    const res = await apiGet<{ classes: { id: string; name: string; section?: string }[] }>(url);
    return res.classes ?? [];
  },

  createStructure: async (data: CreateStructureInput) => {
    const res = await apiPost<{ fee_structure: FeeStructure }>("/api/finance/structures", {
      name: data.name,
      academic_year_id: data.academic_year_id,
      due_date: data.due_date,
      components: data.components,
      class_ids: data.class_ids,
    });
    return res.fee_structure;
  },

  updateStructure: async (id: string, data: UpdateStructureInput) => {
    const res = await apiPut<{ fee_structure: FeeStructure }>(
      `/api/finance/structures/${id}`,
      {
        name: data.name,
        due_date: data.due_date,
        class_ids: data.class_ids,
        components: data.components,
      }
    );
    return res.fee_structure;
  },

  deleteStructure: async (id: string) => {
    await apiDelete(`/api/finance/structures/${id}`);
  },

  assignStructure: async (structureId: string, studentIds: string[]) => {
    const res = await apiPost<{ created_count: number }>(
      `/api/finance/structures/${structureId}/assign`,
      { student_ids: studentIds }
    );
    return res;
  },

  // Student fees
  getStudentFees: async (params?: {
    student_id?: string;
    fee_structure_id?: string;
    status?: string;
    academic_year_id?: string;
    class_id?: string;
    search?: string;
  }) => {
    let url = "/api/finance/student-fees";
    if (params) {
      const q = new URLSearchParams();
      if (params.student_id) q.append("student_id", params.student_id);
      if (params.fee_structure_id) q.append("fee_structure_id", params.fee_structure_id);
      if (params.status) q.append("status", params.status);
      if (params.academic_year_id) q.append("academic_year_id", params.academic_year_id);
      if (params.class_id) q.append("class_id", params.class_id);
      if (params.search) q.append("search", params.search);
      const qs = q.toString();
      if (qs) url += `?${qs}`;
    }
    const res = await apiGet<{ student_fees: StudentFee[] }>(url);
    return res.student_fees ?? [];
  },

  getStudentFee: async (id: string) => {
    return await apiGet<StudentFee>(`/api/finance/student-fees/${id}`);
  },

  deleteStudentFee: async (id: string) => {
    await apiDelete(`/api/finance/student-fees/${id}`);
  },

  getRecentPayments: async (limit = 10) => {
    const res = await apiGet<{ recent_payments: Array<{ id: string; amount: number; student_name?: string; created_at: string }> }>(
      `/api/finance/recent-payments?limit=${limit}`
    );
    return res.recent_payments ?? [];
  },

  // Payments
  recordPayment: async (data: RecordPaymentInput) => {
    const body: Record<string, unknown> = {
      student_fee_id: data.student_fee_id,
      amount: data.amount,
      method: data.method || "cash",
      reference_number: data.reference_number || null,
      notes: data.notes || null,
    };
    if (data.allocations && data.allocations.length > 0) {
      body.allocations = data.allocations.map((a) => ({ item_id: a.item_id, amount: a.amount }));
    }
    const res = await apiPost<{ payment: { id: string }; student_fee: StudentFee }>(
      "/api/finance/payments",
      body
    );
    return res;
  },

  refundPayment: async (paymentId: string, notes?: string) => {
    await apiPost(`/api/finance/payments/${paymentId}/refund`, { notes: notes || null });
  },
};
