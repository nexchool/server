import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { financeService } from "../services/financeService";
import { academicYearService } from "../services/academicYearService";
import { financeClassService } from "../services/classService";
import { studentService } from "@/modules/students/services/studentService";
import type {
  CreateStructureInput,
  UpdateStructureInput,
  RecordPaymentInput,
} from "../types";

const KEYS = {
  structures: ["finance", "structures"] as const,
  structure: (id: string) => ["finance", "structure", id] as const,
  studentFees: ["finance", "studentFees"] as const,
  studentFee: (id: string) => ["finance", "studentFee", id] as const,
  academicYears: ["academics", "academicYears"] as const,
  classes: ["classes"] as const,
};

export function useStructures(params?: {
  academic_year_id?: string;
  class_id?: string;
}) {
  return useQuery({
    queryKey: [...KEYS.structures, params?.academic_year_id ?? "", params?.class_id ?? ""],
    queryFn: () => financeService.getStructures(params),
  });
}

export function useStructure(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: KEYS.structure(id ?? ""),
    queryFn: () => financeService.getStructure(id!),
    enabled: !!id && enabled,
  });
}

export function useAvailableClassesForStructure(
  academicYearId: string | undefined,
  excludeStructureId?: string | null,
  enabled = true
) {
  return useQuery({
    queryKey: [
      "finance",
      "availableClasses",
      academicYearId ?? "",
      excludeStructureId ?? "",
    ],
    queryFn: () =>
      financeService.getAvailableClassesForStructure(
        academicYearId!,
        excludeStructureId
      ),
    enabled: !!academicYearId && enabled,
  });
}

export function useCreateStructure() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateStructureInput) => financeService.createStructure(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.structures });
      qc.invalidateQueries({ queryKey: ["finance", "availableClasses"] });
    },
  });
}

export function useUpdateStructure() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateStructureInput }) =>
      financeService.updateStructure(id, data),
    onSuccess: (_, { id }) => {
      qc.invalidateQueries({ queryKey: KEYS.structures });
      qc.invalidateQueries({ queryKey: KEYS.structure(id) });
      qc.invalidateQueries({ queryKey: ["finance", "availableClasses"] });
      qc.invalidateQueries({ queryKey: KEYS.studentFees });
    },
  });
}

export function useDeleteStructure() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => financeService.deleteStructure(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.structures });
      qc.invalidateQueries({ queryKey: ["finance", "availableClasses"] });
    },
  });
}

export function useAssignStructure() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      structureId,
      studentIds,
    }: {
      structureId: string;
      studentIds: string[];
    }) => financeService.assignStructure(structureId, studentIds),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: KEYS.structures }),
        qc.invalidateQueries({
          queryKey: KEYS.studentFees,
          refetchType: "all",
        }),
        qc.invalidateQueries({
          queryKey: ["finance", "recentPayments"],
          refetchType: "all",
        }),
      ]);
    },
  });
}

export function useStudentFees(params?: {
  student_id?: string;
  fee_structure_id?: string;
  status?: string;
  academic_year_id?: string;
  class_id?: string;
  search?: string;
}) {
  return useQuery({
    queryKey: [
      ...KEYS.studentFees,
      params?.student_id ?? "",
      params?.fee_structure_id ?? "",
      params?.status ?? "",
      params?.academic_year_id ?? "",
      params?.class_id ?? "",
      params?.search ?? "",
    ],
    queryFn: () => financeService.getStudentFees(params),
  });
}

export function useStudentFee(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: KEYS.studentFee(id ?? ""),
    queryFn: () => financeService.getStudentFee(id!),
    enabled: !!id && enabled,
  });
}

export function useDeleteStudentFee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => financeService.deleteStudentFee(id),
    onSuccess: async (_, id) => {
      await Promise.all([
        qc.invalidateQueries({
          queryKey: KEYS.studentFees,
          refetchType: "all",
        }),
        qc.invalidateQueries({ queryKey: KEYS.studentFee(id) }),
        qc.invalidateQueries({
          queryKey: ["finance", "recentPayments"],
          refetchType: "all",
        }),
      ]);
    },
  });
}

export function useRecentPayments(limit = 10) {
  return useQuery({
    queryKey: ["finance", "recentPayments", limit],
    queryFn: () => financeService.getRecentPayments(limit),
  });
}

export function useRecordPayment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: RecordPaymentInput) => financeService.recordPayment(data),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: KEYS.studentFees });
      qc.invalidateQueries({ queryKey: KEYS.studentFee(vars.student_fee_id) });
      qc.invalidateQueries({ queryKey: ["finance", "recentPayments"] });
    },
  });
}

export function useRefundPayment(studentFeeId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ paymentId, notes }: { paymentId: string; notes?: string }) =>
      financeService.refundPayment(paymentId, notes),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["finance"] });
      qc.invalidateQueries({ queryKey: ["finance", "recentPayments"] });
      if (studentFeeId) {
        qc.invalidateQueries({ queryKey: KEYS.studentFee(studentFeeId) });
      }
    },
  });
}

export function useAcademicYears(activeOnly = false) {
  return useQuery({
    queryKey: [...KEYS.academicYears, activeOnly],
    queryFn: () => academicYearService.getAcademicYears(activeOnly),
  });
}

export function useClasses() {
  return useQuery({
    queryKey: KEYS.classes,
    queryFn: () => financeClassService.getClasses(),
  });
}

export function useStudentsForAssign(
  params?: { class_ids?: string[]; search?: string },
  enabled = true
) {
  return useQuery({
    queryKey: [
      "students",
      "assign",
      params?.class_ids?.join(",") ?? "all",
      params?.search ?? "",
    ],
    queryFn: () =>
      studentService.getStudents({
        class_ids: params?.class_ids?.length ? params.class_ids : undefined,
        search: params?.search,
      }),
    enabled,
  });
}
