import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  TextInput,
  Modal,
  Alert,
  SafeAreaView,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import {
  useStudentFee,
  useRecordPayment,
  useRefundPayment,
  useDeleteStudentFee,
} from "@/modules/finance/hooks/useFinance";
import type { RecordPaymentInput } from "@/modules/finance/types";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";

function formatCurrency(n: number) {
  return `₹${n.toLocaleString("en-IN")}`;
}

function formatDate(s: string) {
  try {
    return new Date(s).toLocaleDateString("en-IN");
  } catch {
    return s;
  }
}

// Allocation state: { item_id: amount_string }
type AllocationState = Record<string, string>;

export default function StudentFeeDetailPage() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [paymentModalOpen, setPaymentModalOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("cash");
  const [referenceNumber, setReferenceNumber] = useState("");
  const [notes, setNotes] = useState("");
  const [allocations, setAllocations] = useState<AllocationState>({});
  const [refundModalOpen, setRefundModalOpen] = useState(false);
  const [refundPaymentId, setRefundPaymentId] = useState<string | null>(null);
  const [refundReason, setRefundReason] = useState("");

  const { data, isLoading, error, refetch, isRefetching } = useStudentFee(id);
  const recordMut = useRecordPayment();
  const refundMut = useRefundPayment(id);
  const deleteFeeMut = useDeleteStudentFee();

  const remaining = (data?.total_amount ?? 0) - (data?.paid_amount ?? 0);
  const itemsWithRemaining = (data?.items ?? []).filter(
    (item) => (item.amount ?? 0) - (item.paid_amount ?? 0) > 0
  );

  const amountNum = parseFloat(amount) || 0;
  const amountExceedsRemaining = amountNum > remaining && amount.trim() !== "";
  const allocationSum = itemsWithRemaining.reduce(
    (sum, item) => sum + (parseFloat(allocations[item.id] ?? "0") || 0),
    0
  );
  const useAllocations = allocationSum > 0;
  const allocationMismatch = useAllocations && Math.abs(allocationSum - amountNum) > 0.01;
  const canSubmitPayment =
    !recordMut.isPending &&
    amountNum > 0 &&
    amountNum <= remaining &&
    (!useAllocations || !allocationMismatch);

  const handleQuickAmount = (ratio: number) => {
    const amt = Math.round(remaining * ratio);
    setAmount(String(amt));
  };

  const handlePayFullForItem = (item: { id: string; amount?: number; paid_amount?: number }) => {
    const itemRemaining = (item.amount ?? 0) - (item.paid_amount ?? 0);
    if (itemRemaining > 0) {
      setAllocations((prev) => {
        const next = { ...prev, [item.id]: String(itemRemaining) };
        const sum = Object.values(next).reduce((s, v) => s + (parseFloat(v) || 0), 0);
        setAmount(String(sum));
        return next;
      });
    }
  };

  const handleAutoAllocate = () => {
    if (!amountNum || amountNum <= 0 || amountNum > remaining) return;
    const newAllocations: AllocationState = {};
    let left = amountNum;
    for (const item of itemsWithRemaining) {
      if (left <= 0) break;
      const itemRemaining = (item.amount ?? 0) - (item.paid_amount ?? 0);
      if (itemRemaining <= 0) continue;
      const toApply = Math.min(left, itemRemaining);
      newAllocations[item.id] = String(toApply);
      left -= toApply;
    }
    setAllocations(newAllocations);
  };

  const clearAllocations = () => setAllocations({});

  const handleRecordPayment = async () => {
    const amt = parseFloat(amount);
    if (!id || isNaN(amt) || amt <= 0) {
      Alert.alert("Error", "Enter a valid amount");
      return;
    }
    if (amt > remaining) {
      return; // Handled by disabled state and inline error
    }
    if (useAllocations && allocationMismatch) {
      Alert.alert("Error", "Allocation amounts must sum to the total payment amount");
      return;
    }
    try {
      const payload: RecordPaymentInput = {
        student_fee_id: id,
        amount: amt,
        method,
        reference_number: referenceNumber || undefined,
        notes: notes || undefined,
      };
      if (useAllocations) {
        payload.allocations = itemsWithRemaining
          .filter((item) => parseFloat(allocations[item.id] ?? "0") > 0)
          .map((item) => ({
            item_id: item.id,
            amount: parseFloat(allocations[item.id] ?? "0") || 0,
          }));
      }
      await recordMut.mutateAsync(payload);
      setPaymentModalOpen(false);
      setAmount("");
      setReferenceNumber("");
      setNotes("");
      setAllocations({});
    } catch (e: any) {
      Alert.alert("Error", e?.message ?? "Failed to record payment");
    }
  };

  const openRefundModal = (paymentId: string) => {
    setRefundPaymentId(paymentId);
    setRefundReason("");
    setRefundModalOpen(true);
  };

  const handleRefund = async () => {
    if (!refundPaymentId) return;
    try {
      await refundMut.mutateAsync({
        paymentId: refundPaymentId,
        notes: refundReason.trim() || undefined,
      });
      setRefundModalOpen(false);
      setRefundPaymentId(null);
      setRefundReason("");
    } catch (e: any) {
      Alert.alert("Error", e?.message ?? "Failed to refund");
    }
  };

  const handleRemoveFromStructure = async () => {
    if (!id) return;
    Alert.alert(
      "Remove from Fee Structure",
      "This will remove this student from the fee structure as long as there are no successful payments recorded. Continue?",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: async () => {
            try {
              await deleteFeeMut.mutateAsync(id);
              Alert.alert(
                "Success",
                "Student removed from fee structure.",
                [
                  {
                    text: "OK",
                    onPress: () =>
                      router.replace("/(protected)/finance/student-fees" as any),
                  },
                ],
                { cancelable: false }
              );
            } catch (e: any) {
              Alert.alert("Error", e?.message ?? "Failed to remove student from fee structure");
            }
          },
        },
      ]
    );
  };

  if (error) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.center}>
          <Text style={styles.errorText}>
            {error instanceof Error ? error.message : "Failed to load"}
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  if (isLoading && !data) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.center}>
          <ActivityIndicator size="large" color={Colors.primary} />
        </View>
      </SafeAreaView>
    );
  }

  if (!data) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.center}>
          <Text style={styles.errorText}>Not found</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backIcon}>
          <Ionicons name="arrow-back" size={24} color={Colors.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Fee Detail</Text>
      </View>

      <ScrollView
        style={styles.content}
        contentContainerStyle={styles.contentContainer}
        refreshControl={
          <RefreshControl refreshing={isRefetching} onRefresh={refetch} />
        }
      >
      {/* Summary card */}
      <View style={styles.section}>
        <View style={styles.summaryHeaderRow}>
          <Text style={styles.sectionTitle}>Summary</Text>
          <TouchableOpacity
            onPress={handleRemoveFromStructure}
            style={styles.removeFeeBtn}
          >
            <Ionicons name="trash-outline" size={18} color={Colors.error} />
            <Text style={styles.removeFeeBtnText}>Remove from structure</Text>
          </TouchableOpacity>
        </View>
      <View style={styles.card}>
        <Text style={styles.summaryName}>{data.student_name ?? "—"}</Text>
        <Text style={styles.summaryStructure}>{data.fee_structure_name ?? "—"}</Text>
        <View style={styles.summaryRow}>
          <Text style={styles.summaryLabel}>Total</Text>
          <Text style={[styles.summaryValue, styles.summaryValueFlex]}>
            {formatCurrency(data.total_amount)}
          </Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={styles.summaryLabel}>Paid</Text>
          <Text style={[styles.summaryValue, { color: Colors.success }, styles.summaryValueFlex]}>
            {formatCurrency(data.paid_amount)}
          </Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={styles.summaryLabel}>Remaining</Text>
          <Text style={[styles.summaryValue, { color: Colors.warning }, styles.summaryValueFlex]}>
            {formatCurrency(remaining)}
          </Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={styles.summaryLabel}>Status</Text>
          <View
            style={[
              styles.statusBadge,
              {
                backgroundColor:
                  data.status === "paid"
                    ? Colors.success
                    : data.status === "overdue"
                      ? Colors.error
                      : Colors.warning,
              },
            ]}
          >
            <Text style={styles.statusText}>{data.status}</Text>
          </View>
        </View>
        {remaining > 0 && (
          <TouchableOpacity
            style={styles.recordBtn}
            onPress={() => setPaymentModalOpen(true)}
          >
            <Ionicons name="card-outline" size={20} color={Colors.background} />
            <Text style={styles.recordBtnText}>Record Payment</Text>
          </TouchableOpacity>
        )}
      </View>
      </View>

      {/* Fee items table */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Fee Items</Text>
        {(data.items ?? []).map((item) => (
          <View key={item.id} style={styles.itemRow}>
            <View style={styles.itemMain}>
              <Text style={styles.itemName}>{item.component_name ?? "—"}</Text>
              <Text style={styles.itemMeta}>
                {formatCurrency(item.amount)} • Paid {formatCurrency(item.paid_amount)}
              </Text>
            </View>
            <Text style={styles.itemRemaining}>
              {formatCurrency((item.amount ?? 0) - (item.paid_amount ?? 0))} left
            </Text>
          </View>
        ))}
        {(data.items ?? []).length === 0 && (
          <Text style={styles.emptyText}>No fee items</Text>
        )}
      </View>

      {/* Payment history */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Payment History</Text>
        {(data.payments ?? []).map((p) => (
          <View key={p.id} style={styles.paymentRow}>
            <View style={styles.paymentMain}>
              <Text style={styles.paymentAmount}>{formatCurrency(p.amount)}</Text>
              <Text style={styles.paymentMeta}>
                {p.method} • {formatDate(p.created_at)}
                {p.reference_number ? ` • ${p.reference_number}` : ""}
              </Text>
            </View>
            <View style={styles.paymentRight}>
              <View
                style={[
                  styles.paymentStatus,
                  {
                    backgroundColor:
                      p.status === "success"
                        ? Colors.success
                        : p.status === "refunded"
                          ? Colors.textSecondary
                          : Colors.error,
                  },
                ]}
              >
                <Text style={styles.paymentStatusText}>{p.status}</Text>
              </View>
              {p.status === "success" && (
                <TouchableOpacity
                  onPress={() => openRefundModal(p.id)}
                  style={styles.refundBtn}
                >
                  <Ionicons name="arrow-undo-outline" size={18} color={Colors.error} />
                  <Text style={styles.refundBtnText}>Refund</Text>
                </TouchableOpacity>
              )}
            </View>
          </View>
        ))}
        {(data.payments ?? []).length === 0 && (
          <Text style={styles.emptyText}>No payments yet</Text>
        )}
      </View>

      {/* Record Payment Modal */}
      <Modal visible={paymentModalOpen} animationType="slide" transparent>
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Record Payment</Text>
              <TouchableOpacity
                onPress={() => {
                  setPaymentModalOpen(false);
                  setAllocations({});
                }}
              >
                <Ionicons name="close" size={24} color={Colors.text} />
              </TouchableOpacity>
            </View>
            <ScrollView style={styles.modalBody} showsVerticalScrollIndicator={false}>
              <View style={styles.remainingCard}>
                <Text style={styles.remainingLabel}>Remaining balance</Text>
                <Text style={styles.remainingAmount}>{formatCurrency(remaining)}</Text>
              </View>
              <Text style={styles.inputLabel}>Amount</Text>
              <View style={styles.quickAmountRow}>
                <Pressable
                  style={({ pressed }) => [
                    styles.quickAmountBtn,
                    pressed && styles.quickAmountBtnPressed,
                  ]}
                  onPress={() => handleQuickAmount(1)}
                >
                  <Text style={styles.quickAmountBtnText}>Full</Text>
                  <Text style={styles.quickAmountBtnSub}>{formatCurrency(remaining)}</Text>
                </Pressable>
                <Pressable
                  style={({ pressed }) => [
                    styles.quickAmountBtn,
                    pressed && styles.quickAmountBtnPressed,
                  ]}
                  onPress={() => handleQuickAmount(0.5)}
                >
                  <Text style={styles.quickAmountBtnText}>Half</Text>
                  <Text style={styles.quickAmountBtnSub}>
                    {formatCurrency(Math.round(remaining * 0.5))}
                  </Text>
                </Pressable>
                <Pressable
                  style={({ pressed }) => [
                    styles.quickAmountBtn,
                    pressed && styles.quickAmountBtnPressed,
                  ]}
                  onPress={() => handleQuickAmount(0.25)}
                >
                  <Text style={styles.quickAmountBtnText}>Quarter</Text>
                  <Text style={styles.quickAmountBtnSub}>
                    {formatCurrency(Math.round(remaining * 0.25))}
                  </Text>
                </Pressable>
              </View>
              <TextInput
                style={[
                  styles.input,
                  amountExceedsRemaining && styles.inputError,
                ]}
                value={amount}
                onChangeText={setAmount}
                placeholder={`Or enter custom amount (max ${formatCurrency(remaining)})`}
                keyboardType="decimal-pad"
              />
              {amountExceedsRemaining && (
                <Text style={styles.validationError}>
                  Amount cannot exceed remaining balance
                </Text>
              )}
              {itemsWithRemaining.length > 0 && amountNum > 0 && (
                <>
                  <View style={styles.allocationHeader}>
                    <Text style={styles.inputLabel}>Split by component (optional)</Text>
                    <Text style={styles.allocationHint}>
                      Specify how much goes to each fee item
                    </Text>
                    <View style={styles.allocationActions}>
                      <TouchableOpacity
                        onPress={handleAutoAllocate}
                        style={styles.allocationLink}
                      >
                        <Ionicons name="flash-outline" size={16} color={Colors.primary} />
                        <Text style={styles.linkText}>Auto-fill</Text>
                      </TouchableOpacity>
                      {Object.keys(allocations).length > 0 && (
                        <TouchableOpacity onPress={clearAllocations} style={styles.allocationLink}>
                          <Ionicons name="close-circle-outline" size={16} color={Colors.textSecondary} />
                          <Text style={styles.linkTextSecondary}>Clear</Text>
                        </TouchableOpacity>
                      )}
                    </View>
                  </View>
                  {itemsWithRemaining.map((item) => {
                    const itemRemaining = (item.amount ?? 0) - (item.paid_amount ?? 0);
                    return (
                      <View key={item.id} style={styles.allocationItemRow}>
                        <View style={styles.allocationItemLeft}>
                          <Text style={styles.allocationItemName} numberOfLines={1}>
                            {item.component_name ?? "—"}
                          </Text>
                          <Text style={styles.allocationItemMeta}>
                            {formatCurrency(itemRemaining)} left
                          </Text>
                        </View>
                        <View style={styles.allocationItemRight}>
                          <TextInput
                            style={styles.allocationInput}
                            value={allocations[item.id] ?? ""}
                            onChangeText={(v) =>
                              setAllocations((prev) => ({ ...prev, [item.id]: v }))
                            }
                            placeholder="0"
                            keyboardType="decimal-pad"
                          />
                          <TouchableOpacity
                            style={styles.payFullBtn}
                            onPress={() => handlePayFullForItem(item)}
                          >
                            <Text style={styles.payFullBtnText}>Pay full</Text>
                          </TouchableOpacity>
                        </View>
                      </View>
                    );
                  })}
                  {useAllocations && allocationMismatch && (
                    <Text style={styles.validationError}>
                      Allocation sum ({formatCurrency(allocationSum)}) must equal total ({formatCurrency(amountNum)})
                    </Text>
                  )}
                </>
              )}
              <Text style={styles.inputLabel}>Payment method</Text>
              <View style={styles.methodRow}>
                {[
                  { id: "cash", label: "Cash", icon: "cash-outline" },
                  { id: "online", label: "Online", icon: "phone-portrait-outline" },
                  { id: "bank_transfer", label: "Bank", icon: "business-outline" },
                ].map((m) => (
                  <TouchableOpacity
                    key={m.id}
                    style={[styles.methodChip, method === m.id && styles.methodChipActive]}
                    onPress={() => setMethod(m.id)}
                  >
                    <Ionicons
                      name={m.icon as any}
                      size={18}
                      color={method === m.id ? "#fff" : Colors.textSecondary}
                    />
                    <Text
                      style={[
                        styles.methodChipText,
                        method === m.id && styles.methodChipTextActive,
                      ]}
                    >
                      {m.label}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
              <Text style={styles.inputLabel}>Reference (optional)</Text>
              <TextInput
                style={styles.input}
                value={referenceNumber}
                onChangeText={setReferenceNumber}
                placeholder="Transaction ID or receipt number"
              />
              <Text style={styles.inputLabel}>Notes (optional)</Text>
              <TextInput
                style={[styles.input, styles.notesInput]}
                value={notes}
                onChangeText={setNotes}
                placeholder="Add a note for your records"
              />
            </ScrollView>
            <View style={styles.modalFooter}>
              <TouchableOpacity
                style={styles.cancelBtn}
                onPress={() => {
                  setPaymentModalOpen(false);
                  setAllocations({});
                }}
              >
                <Text style={styles.cancelBtnText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[
                  styles.submitBtn,
                  (!canSubmitPayment || recordMut.isPending) && styles.submitBtnDisabled,
                ]}
                onPress={handleRecordPayment}
                disabled={!canSubmitPayment || recordMut.isPending}
              >
                {recordMut.isPending ? (
                  <ActivityIndicator size="small" color={Colors.background} />
                ) : (
                  <Text style={styles.submitBtnText}>Record</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Refund Confirmation Modal */}
      <Modal visible={refundModalOpen} animationType="slide" transparent>
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Refund Payment</Text>
              <TouchableOpacity
                onPress={() => {
                  setRefundModalOpen(false);
                  setRefundPaymentId(null);
                }}
              >
                <Ionicons name="close" size={24} color={Colors.text} />
              </TouchableOpacity>
            </View>
            <View style={styles.modalBody}>
              <View style={styles.refundWarning}>
                <Ionicons name="warning" size={32} color={Colors.error} />
                <Text style={styles.refundWarningText}>
                  This action cannot be undone. The payment will be marked as refunded and the
                  student fee balance will be adjusted.
                </Text>
              </View>
              <Text style={styles.inputLabel}>Reason (optional)</Text>
              <TextInput
                style={styles.input}
                value={refundReason}
                onChangeText={setRefundReason}
                placeholder="e.g. Duplicate payment, Wrong amount"
                multiline
              />
            </View>
            <View style={styles.modalFooter}>
              <TouchableOpacity
                style={styles.cancelBtn}
                onPress={() => {
                  setRefundModalOpen(false);
                  setRefundPaymentId(null);
                }}
              >
                <Text style={styles.cancelBtnText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[
                  styles.refundSubmitBtn,
                  refundMut.isPending && styles.submitBtnDisabled,
                ]}
                onPress={handleRefund}
                disabled={refundMut.isPending}
              >
                {refundMut.isPending ? (
                  <ActivityIndicator size="small" color={Colors.background} />
                ) : (
                  <Text style={styles.refundSubmitBtnText}>Confirm Refund</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  content: { flex: 1 },
  contentContainer: { paddingBottom: Spacing.xxl },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  backIcon: { padding: Spacing.sm, marginRight: Spacing.sm },
  headerTitle: { fontSize: 24, fontWeight: "bold", color: Colors.text },
  section: { padding: Spacing.lg },
  sectionTitle: { fontSize: 20, fontWeight: "600", color: Colors.text, marginBottom: Spacing.md },
  summaryHeaderRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: Spacing.md,
  },
  card: {
    padding: Spacing.lg,
    backgroundColor: Colors.background,
    borderRadius: Layout.borderRadius.md,
    borderWidth: 1,
    borderColor: Colors.borderLight,
  },
  summaryName: { fontSize: 20, fontWeight: "700", color: Colors.text },
  summaryStructure: { fontSize: 14, color: Colors.textSecondary, marginTop: 2 },
  summaryRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: Spacing.md,
  },
  summaryLabel: { fontSize: 15, color: Colors.textSecondary },
  summaryValue: { fontSize: 15, fontWeight: "600", color: Colors.text },
  summaryValueFlex: { flex: 1, marginLeft: Spacing.sm, textAlign: "right" },
  statusBadge: {
    paddingHorizontal: Spacing.sm,
    paddingVertical: 2,
    borderRadius: Layout.borderRadius.sm,
  },
  statusText: { fontSize: 12, fontWeight: "600", color: Colors.background },
  recordBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: Colors.primary,
    padding: Spacing.md,
    borderRadius: Layout.borderRadius.md,
    marginTop: Spacing.lg,
  },
  recordBtnText: { fontSize: 16, fontWeight: "600", color: Colors.background, marginLeft: Spacing.sm },
  removeFeeBtn: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: Spacing.sm,
    paddingVertical: Spacing.xs,
    borderRadius: Layout.borderRadius.sm,
  },
  removeFeeBtnText: {
    marginLeft: Spacing.xs,
    fontSize: 13,
    color: Colors.error,
    fontWeight: "500",
  },
  itemRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: Spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  itemMain: {},
  itemName: { fontSize: 15, fontWeight: "500", color: Colors.text },
  itemMeta: { fontSize: 12, color: Colors.textSecondary },
  itemRemaining: { fontSize: 14, color: Colors.warning },
  paymentRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  paymentMain: {},
  paymentAmount: { fontSize: 16, fontWeight: "600", color: Colors.text },
  paymentMeta: { fontSize: 12, color: Colors.textSecondary },
  paymentRight: { alignItems: "flex-end" },
  paymentStatus: {
    paddingHorizontal: Spacing.sm,
    paddingVertical: 2,
    borderRadius: Layout.borderRadius.sm,
    marginBottom: Spacing.xs,
  },
  paymentStatusText: { fontSize: 11, fontWeight: "600", color: Colors.background },
  refundBtn: { flexDirection: "row", alignItems: "center" },
  refundBtnText: { fontSize: 13, color: Colors.error, marginLeft: Spacing.xs },
  emptyText: { color: Colors.textSecondary, fontSize: 14 },
  center: { flex: 1, justifyContent: "center", alignItems: "center" },
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
  modalBody: { padding: Spacing.lg, maxHeight: 420 },
  modalFooter: {
    flexDirection: "row",
    gap: Spacing.md,
    padding: Spacing.lg,
    borderTopWidth: 1,
    borderTopColor: Colors.borderLight,
  },
  remainingCard: {
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.md,
    padding: Spacing.md,
    marginBottom: Spacing.lg,
  },
  remainingLabel: { fontSize: 13, color: Colors.textSecondary },
  remainingAmount: { fontSize: 22, fontWeight: "700", color: Colors.warning, marginTop: 2 },
  quickAmountRow: {
    flexDirection: "row",
    gap: Spacing.sm,
    marginBottom: Spacing.md,
  },
  quickAmountBtn: {
    flex: 1,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.md,
    paddingVertical: Spacing.md,
    paddingHorizontal: Spacing.sm,
    alignItems: "center",
    borderWidth: 1,
    borderColor: Colors.borderLight,
  },
  quickAmountBtnPressed: { opacity: 0.8 },
  quickAmountBtnText: { fontSize: 14, fontWeight: "600", color: Colors.text },
  quickAmountBtnSub: { fontSize: 11, color: Colors.textSecondary, marginTop: 2 },
  notesInput: { minHeight: 60 },
  validationError: { fontSize: 13, color: Colors.error, marginTop: -Spacing.sm, marginBottom: Spacing.md },
  inputError: { borderColor: Colors.error },
  inputLabel: { fontSize: 14, fontWeight: "600", color: Colors.text, marginBottom: Spacing.sm },
  allocationHeader: { marginTop: Spacing.md, marginBottom: Spacing.sm },
  allocationHint: { fontSize: 12, color: Colors.textSecondary, marginTop: 2, marginBottom: Spacing.xs },
  allocationActions: { flexDirection: "row", gap: Spacing.md, marginTop: Spacing.xs },
  allocationLink: { flexDirection: "row", alignItems: "center", gap: 4 },
  linkText: { fontSize: 14, color: Colors.primary, fontWeight: "600" },
  linkTextSecondary: { fontSize: 14, color: Colors.textSecondary },
  allocationItemRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: Spacing.xs,
    marginBottom: Spacing.sm,
  },
  allocationItemLeft: { flex: 1 },
  allocationItemName: { fontSize: 14, fontWeight: "500", color: Colors.text },
  allocationItemMeta: { fontSize: 12, color: Colors.textSecondary },
  allocationItemRight: { flexDirection: "row", alignItems: "center", gap: Spacing.sm },
  allocationInput: {
    width: 70,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: Layout.borderRadius.sm,
    paddingHorizontal: Spacing.sm,
    paddingVertical: Spacing.xs,
    fontSize: 14,
    color: Colors.text,
  },
  payFullBtn: {
    paddingHorizontal: Spacing.sm,
    paddingVertical: Spacing.xs,
    backgroundColor: Colors.primary,
    borderRadius: Layout.borderRadius.sm,
  },
  payFullBtnText: { fontSize: 12, fontWeight: "600", color: Colors.background },
  input: {
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: Layout.borderRadius.md,
    padding: Spacing.md,
    fontSize: 16,
    marginBottom: Spacing.md,
  },
  methodRow: { flexDirection: "row", gap: Spacing.sm, marginBottom: Spacing.md },
  methodChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    borderRadius: Layout.borderRadius.md,
    backgroundColor: Colors.backgroundSecondary,
  },
  methodChipActive: { backgroundColor: Colors.primary },
  methodChipText: { fontSize: 14, color: Colors.text },
  methodChipTextActive: { fontSize: 14, color: Colors.background, fontWeight: "600" },
  cancelBtn: { flex: 1, padding: Spacing.md, alignItems: "center" },
  cancelBtnText: { fontSize: 16, color: Colors.textSecondary },
  submitBtn: {
    flex: 1,
    backgroundColor: Colors.primary,
    padding: Spacing.md,
    borderRadius: Layout.borderRadius.md,
    alignItems: "center",
  },
  submitBtnDisabled: { opacity: 0.7 },
  submitBtnText: { fontSize: 16, fontWeight: "600", color: Colors.background },
  refundWarning: {
    flexDirection: "row",
    alignItems: "flex-start",
    backgroundColor: "rgba(255,59,48,0.1)",
    padding: Spacing.md,
    borderRadius: Layout.borderRadius.md,
    marginBottom: Spacing.lg,
  },
  refundWarningText: {
    flex: 1,
    marginLeft: Spacing.md,
    fontSize: 14,
    color: Colors.text,
    lineHeight: 20,
  },
  refundSubmitBtn: {
    flex: 1,
    backgroundColor: Colors.error,
    padding: Spacing.md,
    borderRadius: Layout.borderRadius.md,
    alignItems: "center",
  },
  refundSubmitBtnText: { fontSize: 16, fontWeight: "600", color: Colors.background },
});
