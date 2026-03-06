import React, { useState, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
  TextInput,
  Modal,
  Alert,
  Switch,
  SafeAreaView,
  FlatList,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import {
  useStructures,
  useAcademicYears,
  useClasses,
  useAvailableClassesForStructure,
  useCreateStructure,
  useUpdateStructure,
  useDeleteStructure,
  useAssignStructure,
  useStudentsForAssign,
  useStudentFees,
  useDeleteStudentFee,
} from "@/modules/finance/hooks/useFinance";
import { useAcademicYearContext } from "@/modules/academics/context/AcademicYearContext";
import type { FeeStructure } from "@/modules/finance/types";
import { studentService } from "@/modules/students/services/studentService";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";
import { ClassSelect } from "@/common/components/ClassSelect";
import { ClassMultiSelect } from "@/common/components/ClassMultiSelect";

function formatDate(s: string) {
  try {
    return new Date(s).toLocaleDateString("en-IN");
  } catch {
    return s;
  }
}

export default function FeeStructuresPage() {
  const router = useRouter();
  const { selectedAcademicYearId: contextYearId } = useAcademicYearContext();
  const [academicYearFilter, setAcademicYearFilter] = useState<string>("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [assignStructureId, setAssignStructureId] = useState<string | null>(null);

  const { data: academicYears = [] } = useAcademicYears(false);
  const { data: classes = [] } = useClasses();

  useEffect(() => {
    if (contextYearId) setAcademicYearFilter((prev) => (prev === "" ? contextYearId : prev));
  }, [contextYearId]);

  const { data: structures = [], isLoading, error, refetch, isRefetching } = useStructures({
    academic_year_id: academicYearFilter || undefined,
  });

  const createMut = useCreateStructure();
  const updateMut = useUpdateStructure();
  const deleteMut = useDeleteStructure();
  const assignMut = useAssignStructure();

  const handleEdit = (s: FeeStructure) => {
    setEditingId(s.id);
    setModalOpen(true);
  };

  const handleDelete = (s: FeeStructure) => {
    Alert.alert(
      "Delete Structure",
      `Delete "${s.name}"? This cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            try {
              await deleteMut.mutateAsync(s.id);
            } catch (e: any) {
              Alert.alert("Error", e?.message ?? "Failed to delete");
            }
          },
        },
      ]
    );
  };

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.errorText}>
          {error instanceof Error ? error.message : "Failed to load"}
        </Text>
      </View>
    );
  }

  const renderStructureItem = ({ item: s }: { item: FeeStructure }) => (
    <View style={styles.classCard}>
      <View style={styles.classIcon}>
        <Ionicons name="layers" size={24} color={Colors.primary} />
      </View>
      <View style={styles.classInfo}>
        <Text style={styles.className}>{s.name}</Text>
        <Text style={styles.classDetail}>
          {s.class_name ?? "All classes"} • Due {formatDate(s.due_date)}
        </Text>
        {s.components?.length ? (
          <View style={styles.statsRow}>
            <View style={styles.stat}>
              <Ionicons name="document-text-outline" size={14} color={Colors.textSecondary} />
              <Text style={styles.statText}>{s.components.length} components</Text>
            </View>
          </View>
        ) : null}
      </View>
      <View style={styles.cardActions}>
        <TouchableOpacity
          onPress={() => setAssignStructureId(s.id)}
          style={styles.actionBtn}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <Ionicons name="people-outline" size={20} color={Colors.primary} />
          <Text style={styles.actionLabel}>Assign</Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={() => handleEdit(s)}
          style={styles.actionBtn}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <Ionicons name="pencil-outline" size={20} color={Colors.primary} />
          <Text style={styles.actionLabel}>Edit</Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={() => handleDelete(s)}
          style={[styles.actionBtn, styles.actionBtnDanger]}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <Ionicons name="trash-outline" size={20} color={Colors.error} />
          <Text style={styles.actionLabelDanger}>Delete</Text>
        </TouchableOpacity>
      </View>
    </View>
  );

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backIcon}>
          <Ionicons name="arrow-back" size={24} color={Colors.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Fee Structures</Text>
        <TouchableOpacity
          style={styles.addButton}
          onPress={() => {
            setEditingId(null);
            setModalOpen(true);
          }}
        >
          <Ionicons name="add" size={24} color={Colors.primary} />
        </TouchableOpacity>
      </View>

      <View style={styles.filterSection}>
        <Text style={styles.filterLabel}>Academic Year</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterScroll}>
          <TouchableOpacity
            style={[styles.filterChip, !academicYearFilter && styles.filterChipActive]}
            onPress={() => setAcademicYearFilter("")}
          >
            <Text style={[styles.filterChipText, !academicYearFilter && styles.filterChipTextActive]}>
              All
            </Text>
          </TouchableOpacity>
          {academicYears.map((ay) => (
            <TouchableOpacity
              key={ay.id}
              style={[styles.filterChip, academicYearFilter === ay.id && styles.filterChipActive]}
              onPress={() => setAcademicYearFilter(academicYearFilter === ay.id ? "" : ay.id)}
            >
              <Text
                style={[
                  styles.filterChipText,
                  academicYearFilter === ay.id && styles.filterChipTextActive,
                ]}
              >
                {ay.name}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>

      {isLoading && structures.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={Colors.primary} />
        </View>
      ) : (
        <FlatList
          data={structures}
          keyExtractor={(item) => item.id}
          renderItem={renderStructureItem}
          contentContainerStyle={styles.listContent}
          refreshControl={
            <RefreshControl refreshing={isRefetching} onRefresh={refetch} />
          }
          ListEmptyComponent={
            <View style={styles.emptyState}>
              <Ionicons name="layers-outline" size={48} color={Colors.textTertiary} />
              <Text style={styles.emptyTitle}>No fee structures yet</Text>
              <Text style={styles.emptySubtext}>
                Create your first fee structure to assign fees to students
              </Text>
              <TouchableOpacity
                style={styles.emptyCta}
                onPress={() => {
                  setEditingId(null);
                  setModalOpen(true);
                }}
              >
                <Ionicons name="add" size={20} color="#fff" />
                <Text style={styles.emptyCtaText}>Create Structure</Text>
              </TouchableOpacity>
            </View>
          }
        />
      )}

        <StructureModal
          visible={modalOpen}
          onClose={() => {
            setModalOpen(false);
            setEditingId(null);
          }}
          editingId={editingId}
          structures={structures}
          academicYears={academicYears}
          allClasses={classes}
          defaultAcademicYearId={contextYearId || undefined}
        onCreate={async (data) => {
          await createMut.mutateAsync(data);
          setModalOpen(false);
        }}
        onUpdate={async (id, data) => {
          await updateMut.mutateAsync({ id, data });
          setModalOpen(false);
          setEditingId(null);
        }}
        isCreating={createMut.isPending}
        isUpdating={updateMut.isPending}
      />

      <AssignStructureModal
        visible={!!assignStructureId}
        onClose={() => setAssignStructureId(null)}
        structureId={assignStructureId}
        structureName={structures.find((s) => s.id === assignStructureId)?.name}
        structureClassIds={structures.find((s) => s.id === assignStructureId)?.class_ids ?? []}
        classes={classes}
        onAssign={async (studentIds) => {
          if (!assignStructureId) return;
          await assignMut.mutateAsync({ structureId: assignStructureId, studentIds });
          setAssignStructureId(null);
        }}
        isAssigning={assignMut.isPending}
      />
    </SafeAreaView>
  );
}

interface StructureModalProps {
  visible: boolean;
  onClose: () => void;
  editingId: string | null;
  structures: FeeStructure[];
  academicYears: { id: string; name: string }[];
  allClasses: { id: string; name: string; section?: string }[];
  defaultAcademicYearId?: string;
  onCreate: (data: any) => Promise<void>;
  onUpdate: (id: string, data: any) => Promise<void>;
  isCreating: boolean;
  isUpdating: boolean;
}

function StructureModal({
  visible,
  onClose,
  editingId,
  structures,
  academicYears,
  allClasses,
  defaultAcademicYearId,
  onCreate,
  onUpdate,
  isCreating,
  isUpdating,
}: StructureModalProps) {
  const editing = editingId
    ? structures.find((s) => s.id === editingId)
    : null;

  const [name, setName] = useState(editing?.name ?? "");
  const [academicYearId, setAcademicYearId] = useState(
    editing?.academic_year_id ?? defaultAcademicYearId ?? ""
  );
  const [classIds, setClassIds] = useState<string[]>(
    editing?.class_ids ?? (editing?.class_id ? [editing.class_id] : [])
  );
  const [dueDate, setDueDate] = useState(editing?.due_date ?? "");
  const [components, setComponents] = useState<{ name: string; amount: string; is_optional: boolean }[]>(
    editing?.components?.map((c) => ({
      name: c.name,
      amount: String(c.amount ?? 0),
      is_optional: c.is_optional ?? false,
    })) ?? [{ name: "", amount: "", is_optional: false }]
  );

  React.useEffect(() => {
    if (visible) {
      setName(editing?.name ?? "");
      setAcademicYearId(editing?.academic_year_id ?? defaultAcademicYearId ?? "");
      setClassIds(editing?.class_ids ?? (editing?.class_id ? [editing.class_id] : []));
      setDueDate(editing?.due_date ?? "");
      setComponents(
        editing?.components?.map((c) => ({
          name: c.name,
          amount: String(c.amount ?? 0),
          is_optional: c.is_optional ?? false,
        })) ?? [{ name: "", amount: "", is_optional: false }]
      );
    }
  }, [visible, editingId, editing, defaultAcademicYearId]);

  const addComponent = () => {
    setComponents([...components, { name: "", amount: "", is_optional: false }]);
  };

  const removeComponent = (i: number) => {
    if (components.length <= 1) return;
    setComponents(components.filter((_, idx) => idx !== i));
  };

  const updateComponent = (i: number, field: string, value: string | boolean) => {
    const next = [...components];
    if (field === "name") next[i] = { ...next[i], name: value as string };
    else if (field === "amount") next[i] = { ...next[i], amount: value as string };
    else if (field === "is_optional") next[i] = { ...next[i], is_optional: value as boolean };
    setComponents(next);
  };

  const handleSubmit = async () => {
    if (!name.trim()) {
      Alert.alert("Error", "Name is required");
      return;
    }
    if (!editingId && !academicYearId) {
      Alert.alert("Error", "Academic year is required");
      return;
    }
    if (!dueDate.trim()) {
      Alert.alert("Error", "Due date is required");
      return;
    }
    const comps = components
      .filter((c) => c.name.trim() && c.amount.trim())
      .map((c) => ({
        name: c.name.trim(),
        amount: parseFloat(c.amount) || 0,
        is_optional: c.is_optional,
      }));
    if (!editingId && comps.length === 0) {
      Alert.alert("Error", "Add at least one component");
      return;
    }
    if (editingId && comps.length === 0) {
      Alert.alert("Error", "At least one component is required");
      return;
    }

    try {
      if (editingId) {
        await onUpdate(editingId, {
          name: name.trim(),
          due_date: dueDate.trim(),
          class_ids: classIds,
          components: comps,
        });
      } else {
        await onCreate({
          name: name.trim(),
          academic_year_id: academicYearId,
          class_ids: classIds,
          due_date: dueDate.trim(),
          components: comps,
        });
      }
    } catch (e: any) {
      Alert.alert("Error", e?.message ?? "Failed to save");
    }
  };

  const effectiveAcademicYearId = academicYearId || (editing?.academic_year_id ?? "");
  const { data: availableClasses = [] } = useAvailableClassesForStructure(
    effectiveAcademicYearId || undefined,
    editingId,
    visible && !!effectiveAcademicYearId
  );
  const classOptions = availableClasses.map((c) => ({
    id: c.id,
    label: c.section ? `${c.name}-${c.section}` : c.name,
    name: c.name,
    section: c.section,
  }));

  return (
    <Modal visible={visible} animationType="slide" transparent>
      <View style={styles.modalOverlay}>
        <View style={styles.modalContent}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>
              {editingId ? "Edit Structure" : "Create Structure"}
            </Text>
            <TouchableOpacity onPress={onClose}>
              <Ionicons name="close" size={24} color={Colors.text} />
            </TouchableOpacity>
          </View>

          <ScrollView style={styles.modalBody} showsVerticalScrollIndicator={false}>
            <Text style={styles.inputLabel}>Structure name</Text>
            <Text style={styles.helperText}>A short name to identify this fee structure</Text>
            <TextInput
              style={styles.input}
              value={name}
              onChangeText={setName}
              placeholder="e.g. Term 1 Fee 2025"
            />

            {!editingId && (
              <>
                <Text style={styles.inputLabel}>Academic Year</Text>
                <ScrollView
                  horizontal
                  showsHorizontalScrollIndicator={false}
                  style={styles.chipRow}
                >
                  {academicYears.map((ay) => (
                    <TouchableOpacity
                      key={ay.id}
                      style={[
                        styles.formChip,
                        academicYearId === ay.id && styles.formChipActive,
                      ]}
                      onPress={() => setAcademicYearId(ay.id)}
                    >
                      <Text
                        style={[
                          styles.formChipText,
                          academicYearId === ay.id && styles.formChipTextActive,
                        ]}
                      >
                        {ay.name}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </ScrollView>
              </>
            )}

            <Text style={styles.inputLabel}>Classes</Text>
            <Text style={styles.helperText}>
              Select one or more classes this fee structure applies to. Each class can belong to only
              one fee structure in an academic year.
            </Text>
            <ClassMultiSelect
              value={classIds}
              onChange={setClassIds}
              options={classOptions}
              placeholder="All classes"
            />

            <Text style={styles.inputLabel}>Due Date</Text>
            <Text style={styles.helperText}>When is the fee due? Use YYYY-MM-DD format.</Text>
            <TextInput
              style={styles.input}
              value={dueDate}
              onChangeText={setDueDate}
              placeholder="e.g. 2025-03-31"
            />

            <View style={styles.componentHeader}>
              <Text style={styles.inputLabel}>Components</Text>
              <TouchableOpacity onPress={addComponent} style={styles.addComponentBtn}>
                <Ionicons name="add" size={20} color={Colors.primary} />
                <Text style={styles.addComponentText}>Add</Text>
              </TouchableOpacity>
            </View>
            {components.map((c, i) => (
              <View key={i} style={styles.componentRow}>
                <TextInput
                  style={[styles.input, styles.componentInput]}
                  value={c.name}
                  onChangeText={(v) => updateComponent(i, "name", v)}
                  placeholder="Component name"
                />
                <TextInput
                  style={[styles.input, styles.amountInput]}
                  value={c.amount}
                  onChangeText={(v) => updateComponent(i, "amount", v)}
                  placeholder="Amount"
                  keyboardType="decimal-pad"
                />
                <View style={styles.optionalRow}>
                  <Text style={styles.optionalLabel}>Optional</Text>
                  <Switch
                    value={c.is_optional}
                    onValueChange={(v) => updateComponent(i, "is_optional", v)}
                  />
                </View>
                <TouchableOpacity
                  onPress={() => removeComponent(i)}
                  disabled={components.length <= 1}
                  style={styles.removeBtn}
                >
                  <Ionicons name="remove-circle-outline" size={22} color={Colors.error} />
                </TouchableOpacity>
              </View>
            ))}
          </ScrollView>

          <View style={styles.modalFooter}>
            <TouchableOpacity style={styles.cancelBtn} onPress={onClose}>
              <Text style={styles.cancelBtnText}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.submitBtn, (isCreating || isUpdating) && styles.submitBtnDisabled]}
              onPress={handleSubmit}
              disabled={isCreating || isUpdating}
            >
              {isCreating || isUpdating ? (
                <ActivityIndicator size="small" color={Colors.background} />
              ) : (
                <Text style={styles.submitBtnText}>
                  {editingId ? "Update" : "Create"}
                </Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

interface AssignStructureModalProps {
  visible: boolean;
  onClose: () => void;
  structureId: string | null;
  structureName?: string;
  structureClassIds?: string[];
  classes: { id: string; name: string; section?: string }[];
  onAssign: (studentIds: string[]) => Promise<void>;
  isAssigning: boolean;
}

function AssignStructureModal({
  visible,
  onClose,
  structureId,
  structureName,
  structureClassIds = [],
  classes,
  onAssign,
  isAssigning,
}: AssignStructureModalProps) {
  const [selectedStudentIds, setSelectedStudentIds] = useState<Set<string>>(new Set());
  const [studentsInitialized, setStudentsInitialized] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const deleteFeeMut = useDeleteStudentFee();

  React.useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchQuery.trim()), 300);
    return () => clearTimeout(t);
  }, [searchQuery]);

  const isAllClassesStructure = structureClassIds.length === 0;
  const allowedClasses = isAllClassesStructure
    ? classes
    : classes.filter((c) => structureClassIds.includes(c.id));
  const effectiveClassIds = isAllClassesStructure
    ? allowedClasses.map((c) => c.id)
    : structureClassIds;

  const { data: displayStudents = [], isLoading: studentsLoading } = useStudentsForAssign(
    visible
      ? {
          class_ids: effectiveClassIds.length > 0 ? effectiveClassIds : undefined,
          search: debouncedSearch || undefined,
        }
      : undefined,
    visible
  );

  const { data: structureFees = [] } = useStudentFees(
    structureId ? { fee_structure_id: structureId } : undefined
  );

  const { assignedStudentIds, assignedFeeIdsByStudent } = React.useMemo(() => {
    const ids = new Set<string>();
    const map = new Map<string, string>();
    if (!structureFees || (structureFees as any[]).length === 0) {
      return { assignedStudentIds: ids, assignedFeeIdsByStudent: map };
    }
    const classFilter = new Set(effectiveClassIds);
    (structureFees as Array<{ id: string; student_id: string; class_id?: string }>).forEach(
      (sf) => {
        if (classFilter.size === 0 || !sf.class_id || classFilter.has(sf.class_id)) {
          ids.add(sf.student_id);
          map.set(sf.student_id, sf.id);
        }
      }
    );
    return { assignedStudentIds: ids, assignedFeeIdsByStudent: map };
  }, [structureFees, effectiveClassIds]);

  React.useEffect(() => {
    if (!visible) {
      setSelectedStudentIds(new Set());
      setStudentsInitialized(false);
      setSearchQuery("");
      setDebouncedSearch("");
    }
  }, [visible]);

  React.useEffect(() => {
    if (!visible || studentsInitialized) return;
    if (assignedStudentIds.size > 0) {
      setSelectedStudentIds(new Set(assignedStudentIds));
    } else {
      setSelectedStudentIds(new Set());
    }
    setStudentsInitialized(true);
  }, [visible, studentsInitialized, assignedStudentIds]);

  const toggleStudent = (id: string) => {
    setSelectedStudentIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleAssign = async () => {
    const selected = new Set(selectedStudentIds);
    const toAdd: string[] = [];
    const toRemoveFeeIds: string[] = [];

    assignedStudentIds.forEach((sid) => {
      if (!selected.has(sid)) {
        const feeId = assignedFeeIdsByStudent.get(sid);
        if (feeId) toRemoveFeeIds.push(feeId);
      }
    });
    selected.forEach((sid) => {
      if (!assignedStudentIds.has(sid)) toAdd.push(sid);
    });

    try {
      if (toRemoveFeeIds.length > 0) {
        await Promise.all(toRemoveFeeIds.map((fid) => deleteFeeMut.mutateAsync(fid)));
      }
      if (toAdd.length > 0) {
        await onAssign(toAdd);
      }
      onClose();
    } catch (e: any) {
      Alert.alert(
        "Error",
        e?.message ??
          "Failed to update student assignments. Some students may have payments recorded and cannot be removed."
      );
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent>
      <View style={styles.modalOverlay}>
        <View style={[styles.modalContent, { maxHeight: "85%" }]}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Assign: {structureName ?? "—"}</Text>
            <TouchableOpacity onPress={onClose}>
              <Ionicons name="close" size={24} color={Colors.text} />
            </TouchableOpacity>
          </View>

          <View style={styles.assignModeSection}>
            <Text style={styles.assignModeLabel}>Assign to students</Text>
            <Text style={styles.helperText}>
              {isAllClassesStructure
                ? "This fee structure applies to all classes."
                : `Structure classes: ${
                    allowedClasses.length
                      ? allowedClasses
                          .map((c) => (c.section ? `${c.name}-${c.section}` : c.name))
                          .join(", ")
                      : "—"
                  }`}
            </Text>
            <Text style={styles.assignModeHint}>
              Select individual students to assign or remove this fee structure
            </Text>
          </View>

          <View style={[styles.modalBody, { paddingBottom: 0 }]}>
            <Text style={styles.inputLabel}>Search students</Text>
            <TextInput
              style={styles.searchInput}
              placeholder="Name, admission number..."
              value={searchQuery}
              onChangeText={setSearchQuery}
              placeholderTextColor={Colors.textTertiary}
            />
            <Text style={[styles.inputLabel, { marginTop: Spacing.md }]}>Select Students</Text>
            <ScrollView style={{ maxHeight: 240 }} showsVerticalScrollIndicator>
              {studentsLoading ? (
                <View style={styles.center}>
                  <ActivityIndicator size="small" color={Colors.primary} />
                </View>
              ) : (
                (displayStudents as Array<{ id: string; name?: string; admission_number?: string }>).map(
                  (s) => (
                    <TouchableOpacity
                      key={s.id}
                      style={[
                        styles.studentSelectRow,
                        selectedStudentIds.has(s.id) && styles.studentSelectRowActive,
                      ]}
                      onPress={() => toggleStudent(s.id)}
                    >
                      <Ionicons
                        name={selectedStudentIds.has(s.id) ? "checkbox" : "square-outline"}
                        size={22}
                        color={selectedStudentIds.has(s.id) ? Colors.primary : Colors.textSecondary}
                      />
                      <Text style={styles.studentSelectName}>
                        {s.name ?? s.admission_number ?? s.id}
                      </Text>
                    </TouchableOpacity>
                  )
                )
              )}
              {!studentsLoading && displayStudents.length === 0 && (
                <Text style={styles.emptyText}>
                  {searchQuery.trim() ? "No students match your search" : "No students"}
                </Text>
              )}
            </ScrollView>
          </View>

          <View style={styles.modalFooter}>
            <TouchableOpacity style={styles.cancelBtn} onPress={onClose}>
              <Text style={styles.cancelBtnText}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.submitBtn, isAssigning && styles.submitBtnDisabled]}
              onPress={handleAssign}
              disabled={isAssigning}
            >
              {isAssigning ? (
                <ActivityIndicator size="small" color={Colors.background} />
              ) : (
                <Text style={styles.submitBtnText}>Assign</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  backIcon: { padding: Spacing.sm, marginRight: Spacing.sm },
  headerTitle: { flex: 1, fontSize: 24, fontWeight: "bold", color: Colors.text },
  addButton: {
    padding: Spacing.sm,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.md,
  },
  filterSection: {
    padding: Spacing.md,
    backgroundColor: Colors.background,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  filterLabel: { fontSize: 14, color: Colors.textSecondary, marginBottom: Spacing.sm },
  filterScroll: { marginTop: Spacing.xs },
  filterChip: {
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    borderRadius: Layout.borderRadius.md,
    backgroundColor: Colors.backgroundSecondary,
    marginRight: Spacing.sm,
  },
  filterChipActive: { backgroundColor: Colors.primary },
  filterChipText: { fontSize: 14, color: Colors.text },
  filterChipTextActive: { fontSize: 14, color: Colors.background, fontWeight: "600" },
  listContent: { padding: Spacing.md },
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: Spacing.xl },
  emptyText: { color: Colors.textSecondary, fontSize: 16 },
  classCard: {
    flexDirection: "row",
    alignItems: "center",
    padding: Spacing.md,
    backgroundColor: Colors.background,
    borderRadius: Layout.borderRadius.md,
    borderWidth: 1,
    borderColor: Colors.borderLight,
    marginBottom: Spacing.sm,
  },
  classIcon: {
    width: 48,
    height: 48,
    borderRadius: Layout.borderRadius.md,
    backgroundColor: Colors.backgroundSecondary,
    alignItems: "center",
    justifyContent: "center",
    marginRight: Spacing.md,
  },
  classInfo: { flex: 1 },
  className: { fontSize: 16, fontWeight: "600", color: Colors.text },
  classDetail: { fontSize: 13, color: Colors.textSecondary, marginTop: 2 },
  statsRow: { flexDirection: "row", marginTop: Spacing.xs, gap: Spacing.md },
  stat: { flexDirection: "row", alignItems: "center", gap: 4 },
  statText: { fontSize: 12, color: Colors.textSecondary },
  cardActions: { flexDirection: "row", alignItems: "center", gap: Spacing.xs },
  actionBtn: { alignItems: "center", paddingVertical: Spacing.xs, paddingHorizontal: Spacing.sm },
  actionLabel: { fontSize: 10, color: Colors.primary, marginTop: 2 },
  actionBtnDanger: {},
  actionLabelDanger: { fontSize: 10, color: Colors.error, marginTop: 2 },
  emptyState: {
    alignItems: "center",
    paddingVertical: Spacing.xxl,
  },
  emptyTitle: { fontSize: 18, fontWeight: "600", color: Colors.text, marginTop: Spacing.md },
  emptySubtext: {
    fontSize: 14,
    color: Colors.textSecondary,
    marginTop: Spacing.xs,
    textAlign: "center",
    paddingHorizontal: Spacing.xl,
  },
  emptyCta: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.sm,
    marginTop: Spacing.lg,
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    backgroundColor: Colors.primary,
    borderRadius: Layout.borderRadius.md,
  },
  emptyCtaText: { color: "#fff", fontWeight: "600", fontSize: 15 },
  errorText: { color: Colors.error, fontSize: 16 },

  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "flex-end",
  },
  modalContent: {
    backgroundColor: Colors.background,
    borderTopLeftRadius: Layout.borderRadius.xl,
    borderTopRightRadius: Layout.borderRadius.xl,
    maxHeight: "90%",
  },
  modalHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: Spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  modalTitle: { fontSize: 18, fontWeight: "700", color: Colors.text },
  modalBody: { padding: Spacing.lg, maxHeight: 400 },
  modalFooter: {
    flexDirection: "row",
    gap: Spacing.md,
    padding: Spacing.lg,
    borderTopWidth: 1,
    borderTopColor: Colors.borderLight,
  },
  inputLabel: { fontSize: 14, fontWeight: "600", color: Colors.text, marginBottom: Spacing.sm },
  searchInput: {
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: Layout.borderRadius.md,
    padding: Spacing.md,
    fontSize: 16,
    marginBottom: Spacing.md,
    color: Colors.text,
  },
  helperText: { fontSize: 12, color: Colors.textSecondary, marginBottom: Spacing.sm },
  input: {
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: Layout.borderRadius.md,
    padding: Spacing.md,
    fontSize: 16,
    marginBottom: Spacing.md,
  },
  chipRow: { marginBottom: Spacing.md },
  formChip: {
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    borderRadius: Layout.borderRadius.md,
    backgroundColor: Colors.backgroundSecondary,
    marginRight: Spacing.sm,
  },
  formChipActive: { backgroundColor: Colors.primary },
  formChipText: { fontSize: 14, color: Colors.text },
  formChipTextActive: { fontSize: 14, color: Colors.background, fontWeight: "600" },
  componentHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  componentRow: { flexDirection: "row", alignItems: "center", marginBottom: Spacing.sm },
  componentInput: { flex: 1, marginRight: Spacing.sm },
  amountInput: { width: 90, marginRight: Spacing.sm },
  optionalRow: { flexDirection: "row", alignItems: "center", marginRight: Spacing.sm },
  optionalLabel: { fontSize: 12, color: Colors.textSecondary, marginRight: Spacing.xs },
  removeBtn: { padding: Spacing.sm },
  addComponentBtn: { flexDirection: "row", alignItems: "center" },
  addComponentText: { fontSize: 14, color: Colors.primary, marginLeft: Spacing.xs },
  assignModeSection: {
    paddingHorizontal: Spacing.lg,
    marginBottom: Spacing.md,
  },
  assignModeLabel: { fontSize: 14, fontWeight: "600", color: Colors.text },
  assignModeHint: { fontSize: 12, color: Colors.textSecondary, marginTop: 2, marginBottom: Spacing.sm },
  assignModeRow: { flexDirection: "row", gap: Spacing.sm },
  assignModeChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.xs,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    borderRadius: Layout.borderRadius.md,
    backgroundColor: Colors.backgroundSecondary,
  },
  assignModeText: { fontSize: 14, color: Colors.text },
  assignHint: { fontSize: 13, color: Colors.textSecondary },
  studentSelectRow: {
    flexDirection: "row",
    alignItems: "center",
    padding: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  studentSelectRowActive: { backgroundColor: Colors.backgroundSecondary },
  studentSelectName: { marginLeft: Spacing.md, fontSize: 16 },
  cancelBtn: { flex: 1, padding: Spacing.md, alignItems: "center" },
  cancelBtnText: { fontSize: 16, color: Colors.textSecondary },
  submitBtn: { flex: 1, backgroundColor: Colors.primary, padding: Spacing.md, borderRadius: Layout.borderRadius.md, alignItems: "center" },
  submitBtnDisabled: { opacity: 0.7 },
  submitBtnText: { fontSize: 16, fontWeight: "600", color: Colors.background },
});
