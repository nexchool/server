import React, { useEffect, useState, useCallback, useRef } from "react";
import {
  View,
  Text,
  StyleSheet,
  SafeAreaView,
  ScrollView,
  FlatList,
  TouchableOpacity,
  Modal,
  TextInput,
  Alert,
  ActivityIndicator,
  RefreshControl,
  Animated,
  Dimensions,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";
import { useTeacherLeaves } from "@/modules/teachers/hooks/useTeacherLeaves";
import { TeacherLeave, LeaveBalance, LEAVE_TYPES } from "@/modules/teachers/types";
import { holidayService } from "@/modules/holidays/services/holidayService";
import { Holiday, HOLIDAY_TYPE_LABELS, CreateHolidayDTO } from "@/modules/holidays/types";
import { useHolidays } from "@/modules/holidays/hooks/useHolidays";
import { HolidayFormModal } from "@/modules/holidays/components/HolidayFormModal";
import { usePermissions } from "@/modules/permissions/hooks/usePermissions";
import * as PERMS from "@/modules/permissions/constants/permissions";
import { DateField } from "@/common/components/DateField";

const { width: SW } = Dimensions.get("window");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusColor(s: string) {
  switch (s) {
    case "approved":  return Colors.success;
    case "rejected":  return Colors.error;
    case "cancelled": return Colors.textTertiary;
    default:          return Colors.warning;
  }
}

function fmtDate(iso: string) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function fmtDateShort(iso: string) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

// Deterministic color from a string (for holiday avatars)
const AVATAR_COLORS = [
  ["#4F46E5", "#818CF8"],
  ["#0891B2", "#67E8F9"],
  ["#059669", "#6EE7B7"],
  ["#D97706", "#FCD34D"],
  ["#DC2626", "#FCA5A5"],
  ["#7C3AED", "#C4B5FD"],
  ["#DB2777", "#F9A8D4"],
  ["#0284C7", "#7DD3FC"],
];
function avatarColors(name: string): [string, string] {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffff;
  const pair = AVATAR_COLORS[h % AVATAR_COLORS.length];
  return [pair[0], pair[1]];
}
function initials(name: string) {
  return name.split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() ?? "").join("");
}

// ---------------------------------------------------------------------------
// Sub-tab data
// ---------------------------------------------------------------------------
const DATA_TABS = ["Summary", "Balance", "Requests"] as const;
type DataTab = (typeof DATA_TABS)[number];

const STATUS_FILTERS = [
  { label: "All",       value: "" },
  { label: "Pending",   value: "pending" },
  { label: "Approved",  value: "approved" },
  { label: "Rejected",  value: "rejected" },
  { label: "Cancelled", value: "cancelled" },
];

// ---------------------------------------------------------------------------
// Balance Summary Card  (compact, horizontal)
// ---------------------------------------------------------------------------
function BalanceCard({
  balance,
  onPress,
}: {
  balance: LeaveBalance;
  onPress: () => void;
}) {
  const avail     = balance.is_unlimited ? "∞"  : balance.available_days.toFixed(1);
  const availColor = balance.is_unlimited
    ? Colors.success
    : balance.available_days <= 0
    ? Colors.error
    : balance.available_days <= 2
    ? Colors.warning
    : Colors.success;

  return (
    <TouchableOpacity style={bc.card} onPress={onPress} activeOpacity={0.7}>
      <Text style={bc.typeName} numberOfLines={1}>
        {balance.leave_type.charAt(0).toUpperCase() + balance.leave_type.slice(1)}
      </Text>
      <Text style={[bc.main, { color: availColor }]}>{avail}</Text>
      <Text style={bc.mainLabel}>Available</Text>
      {!balance.is_unlimited && (
        <View style={bc.row}>
          <Text style={[bc.pill, { color: Colors.warning }]}>
            {balance.pending_days.toFixed(1)} Booked
          </Text>
        </View>
      )}
    </TouchableOpacity>
  );
}
const bc = StyleSheet.create({
  card: {
    width: 104,
    marginRight: Spacing.sm,
    paddingHorizontal: 12,
    paddingVertical: 14,
    borderRadius: Layout.borderRadius.md,
    backgroundColor: Colors.backgroundSecondary,
    borderWidth: 1,
    borderColor: Colors.borderLight,
    alignItems: "center",
  },
  typeName: { fontSize: 11, fontWeight: "600", color: Colors.textSecondary, textAlign: "center", marginBottom: 6 },
  main: { fontSize: 24, fontWeight: "800" },
  mainLabel: { fontSize: 10, color: Colors.textTertiary, marginTop: 1, marginBottom: 4 },
  row: { flexDirection: "row", alignItems: "center" },
  pill: { fontSize: 11, fontWeight: "600" },
});

// ---------------------------------------------------------------------------
// Balance Detail Row  (Balance tab)
// ---------------------------------------------------------------------------
function BalanceDetailRow({ b }: { b: LeaveBalance }) {
  const avail = b.is_unlimited ? "∞" : b.available_days.toFixed(1);
  const availColor = b.is_unlimited
    ? Colors.success
    : b.available_days <= 0
    ? Colors.error
    : b.available_days <= 2
    ? Colors.warning
    : Colors.success;

  return (
    <View style={bdr.row}>
      <View style={{ flex: 1 }}>
        <Text style={bdr.name}>
          {b.leave_type.charAt(0).toUpperCase() + b.leave_type.slice(1)} Leave
        </Text>
        {b.is_unlimited ? (
          <Text style={[bdr.unlimited]}>Unlimited</Text>
        ) : (
          <Text style={bdr.sub}>{b.allocated_days + b.carried_forward_days} days allocated · year {b.academic_year}</Text>
        )}
        {b.carried_forward_days > 0 && (
          <Text style={bdr.cf}>+{b.carried_forward_days}d carried forward</Text>
        )}
      </View>
      {!b.is_unlimited && (
        <View style={bdr.nums}>
          <View style={bdr.numCol}>
            <Text style={[bdr.numVal, { color: availColor }]}>{avail}</Text>
            <Text style={bdr.numLabel}>Available</Text>
          </View>
          <View style={bdr.divider} />
          <View style={bdr.numCol}>
            <Text style={[bdr.numVal, { color: Colors.warning }]}>{b.pending_days.toFixed(1)}</Text>
            <Text style={bdr.numLabel}>Pending</Text>
          </View>
          <View style={bdr.divider} />
          <View style={bdr.numCol}>
            <Text style={[bdr.numVal, { color: Colors.error }]}>{b.used_days.toFixed(1)}</Text>
            <Text style={bdr.numLabel}>Used</Text>
          </View>
        </View>
      )}
    </View>
  );
}
const bdr = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: Spacing.lg,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
    gap: Spacing.md,
  },
  name: { fontSize: 15, fontWeight: "600", color: Colors.text },
  sub: { fontSize: 12, color: Colors.textTertiary, marginTop: 2 },
  unlimited: { fontSize: 13, color: Colors.success, fontWeight: "600", marginTop: 2 },
  cf: { fontSize: 11, color: Colors.textSecondary, marginTop: 3, fontStyle: "italic" },
  nums: { flexDirection: "row", alignItems: "center", gap: 2 },
  numCol: { alignItems: "center", width: 54 },
  numVal: { fontSize: 17, fontWeight: "800" },
  numLabel: { fontSize: 9, color: Colors.textTertiary, marginTop: 1 },
  divider: { width: 1, height: 28, backgroundColor: Colors.borderLight },
});

// ---------------------------------------------------------------------------
// Leave Request Row
// ---------------------------------------------------------------------------
function LeaveRow({
  item,
  onCancel,
}: {
  item: TeacherLeave;
  onCancel?: () => void;
}) {
  const days = item.working_days ?? 1;
  const sameDay = item.start_date === item.end_date;
  const dateStr = sameDay
    ? fmtDate(item.start_date)
    : `${fmtDateShort(item.start_date)} – ${fmtDateShort(item.end_date)}`;

  return (
    <View style={lr.row}>
      <View style={{ flex: 1 }}>
        <View style={lr.titleRow}>
          <Text style={lr.type}>
            {item.leave_type.charAt(0).toUpperCase() + item.leave_type.slice(1)} Leave
          </Text>
          <Text style={lr.days}>{days} {days === 1 ? "Day" : "Days"}</Text>
        </View>
        <Text style={lr.date}>{dateStr}</Text>
        <Text style={[lr.status, { color: statusColor(item.status) }]}>
          {item.status.charAt(0).toUpperCase() + item.status.slice(1)}
        </Text>
      </View>
      {item.status === "pending" && onCancel && (
        <TouchableOpacity onPress={onCancel} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
          <Ionicons name="close-circle-outline" size={22} color={Colors.textTertiary} />
        </TouchableOpacity>
      )}
    </View>
  );
}
const lr = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: Spacing.lg,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
    gap: Spacing.sm,
  },
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 3 },
  type: { fontSize: 14, fontWeight: "600", color: Colors.text },
  days: { fontSize: 12, color: Colors.textSecondary },
  date: { fontSize: 12, color: Colors.textSecondary, marginBottom: 2 },
  status: { fontSize: 12, fontWeight: "700" },
});

// ---------------------------------------------------------------------------
// Holiday Row
// ---------------------------------------------------------------------------
interface HolidayRowProps {
  h: Holiday;
  onEdit?: (h: Holiday) => void;
  onDelete?: (h: Holiday) => void;
}
function HolidayRow({ h, onEdit, onDelete }: HolidayRowProps) {
  const [c1] = avatarColors(h.name);
  const abbr = initials(h.name);
  const dateLabel = h.is_recurring
    ? (h.recurring_day_name ?? "Weekly Off")
    : h.is_single_day
    ? fmtDate(h.start_date!)
    : `${fmtDate(h.start_date!)} – ${fmtDate(h.end_date!)}`;

  return (
    <View style={hr.row}>
      <View style={[hr.avatar, { backgroundColor: c1 }]}>
        <Text style={hr.avatarText}>{abbr}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={hr.name}>{h.name}</Text>
        <Text style={hr.date}>{dateLabel}</Text>
      </View>
      {onEdit || onDelete ? (
        <View style={hr.actions}>
          {onEdit && (
            <TouchableOpacity style={hr.actionBtn} onPress={() => onEdit(h)}>
              <Ionicons name="pencil-outline" size={15} color={Colors.textSecondary} />
            </TouchableOpacity>
          )}
          {onDelete && (
            <TouchableOpacity style={hr.actionBtn} onPress={() => onDelete(h)}>
              <Ionicons name="trash-outline" size={15} color={Colors.error} />
            </TouchableOpacity>
          )}
        </View>
      ) : (
        <View style={hr.typeBadge}>
          <Text style={hr.typeText}>{HOLIDAY_TYPE_LABELS[h.holiday_type]}</Text>
        </View>
      )}
    </View>
  );
}
const hr = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: Spacing.lg,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
    gap: Spacing.md,
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 10,
    justifyContent: "center",
    alignItems: "center",
  },
  avatarText: { fontSize: 14, fontWeight: "800", color: "#fff" },
  name: { fontSize: 14, fontWeight: "600", color: Colors.text },
  date: { fontSize: 12, color: Colors.textSecondary, marginTop: 2 },
  typeBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
    backgroundColor: Colors.backgroundSecondary,
    borderWidth: 1,
    borderColor: Colors.borderLight,
  },
  typeText: { fontSize: 10, color: Colors.textSecondary, fontWeight: "600" },
  actions: { flexDirection: "row", gap: 4 },
  actionBtn: {
    padding: 7,
    borderRadius: 8,
    backgroundColor: Colors.backgroundSecondary,
    borderWidth: 1,
    borderColor: Colors.borderLight,
  },
});

// ---------------------------------------------------------------------------
// Apply Leave Modal
// ---------------------------------------------------------------------------
interface ApplyModalProps {
  visible: boolean;
  balances: LeaveBalance[];
  onClose: () => void;
  onSubmit: (dto: {
    start_date: string;
    end_date: string;
    leave_type: string;
    reason?: string;
  }) => Promise<void>;
}

function ApplyModal({ visible, balances, onClose, onSubmit }: ApplyModalProps) {
  const [leaveStart, setLeaveStart] = useState("");
  const [leaveEnd,   setLeaveEnd]   = useState("");
  const [leaveType,  setLeaveType]  = useState("casual");
  const [reason,     setReason]     = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [holidayWarn,setHolidayWarn]= useState<string | null>(null);
  const [checking,   setChecking]   = useState(false);
  const [balErr,     setBalErr]     = useState<string | null>(null);
  const [estDays,    setEstDays]    = useState<number | null>(null);

  const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
  const getBal  = (t: string) => balances.find(b => b.leave_type === t);

  const checkBal = useCallback((t: string, days: number | null) => {
    const bal = balances.find(b => b.leave_type === t);
    if (!bal || bal.is_unlimited || days === null) { setBalErr(null); return; }
    if (!bal.allow_negative && bal.available_days < days) {
      setBalErr(`Only ${bal.available_days.toFixed(1)}d available · ~${days}d needed`);
    } else { setBalErr(null); }
  }, [balances]);

  const checkHols = useCallback(async (start: string, end: string) => {
    if (!DATE_RE.test(start) || !DATE_RE.test(end) || end < start) {
      setHolidayWarn(null); setEstDays(null); return;
    }
    setChecking(true);
    try {
      const sd = new Date(start), ed = new Date(end);
      const [nonRec, rec] = await Promise.all([
        holidayService.getHolidays({ start_date: start, end_date: end, include_recurring: false }),
        holidayService.getRecurring(),
      ]);
      const seen = new Set<number>(); const recHits: Holiday[] = [];
      const cur = new Date(sd);
      while (cur <= ed) {
        const dw = (cur.getDay() + 6) % 7;
        const m  = rec.find(r => r.recurring_day_of_week === dw);
        if (m && !seen.has(dw)) { seen.add(dw); recHits.push(m); }
        cur.setDate(cur.getDate() + 1);
      }
      const total = Math.round((ed.getTime() - sd.getTime()) / 86400000) + 1;
      const hDates = new Set<string>(); let hCount = 0;
      for (const h of nonRec) {
        if (!h.start_date) continue;
        const hs = new Date(Math.max(new Date(h.start_date).getTime(), sd.getTime()));
        const he = new Date(Math.min(new Date(h.end_date || h.start_date).getTime(), ed.getTime()));
        const c = new Date(hs);
        while (c <= he) { const ds = c.toISOString().split("T")[0]; if (!hDates.has(ds)) { hDates.add(ds); hCount++; } c.setDate(c.getDate() + 1); }
      }
      for (const r of recHits) {
        const rc = new Date(sd);
        while (rc <= ed) {
          const dw = (rc.getDay() + 6) % 7; const ds = rc.toISOString().split("T")[0];
          if (dw === r.recurring_day_of_week && !hDates.has(ds)) { hDates.add(ds); hCount++; }
          rc.setDate(rc.getDate() + 1);
        }
      }
      const working = total - hCount;
      setEstDays(working); checkBal(leaveType, working);
      if ([...nonRec, ...recHits].length === 0) { setHolidayWarn(null); return; }
      if (working === 0) setHolidayWarn("All days are holidays — no leave needed.");
      else setHolidayWarn(`${hCount} holiday day(s) excluded. ${working} working day(s) will be counted.`);
    } catch { setHolidayWarn(null); }
    finally { setChecking(false); }
  }, [leaveType, checkBal]);

  const reset = () => {
    setLeaveStart(""); setLeaveEnd(""); setLeaveType("casual"); setReason("");
    setHolidayWarn(null); setBalErr(null); setEstDays(null);
  };

  const onStart = (v: string) => { setLeaveStart(v); if (leaveEnd)  checkHols(v, leaveEnd); };
  const onEnd   = (v: string) => { setLeaveEnd(v);   if (leaveStart) checkHols(leaveStart, v); };
  const onType  = (t: string) => { setLeaveType(t);  checkBal(t, estDays); };

  const selBal   = getBal(leaveType);
  const blocked  = submitting || checking || !!balErr;

  const handleSubmit = async () => {
    if (!leaveStart || !leaveEnd) { Alert.alert("Required", "Enter start and end dates"); return; }
    if (!DATE_RE.test(leaveStart) || !DATE_RE.test(leaveEnd)) { Alert.alert("Format", "Use YYYY-MM-DD"); return; }
    if (leaveEnd < leaveStart) { Alert.alert("Invalid", "End must be on or after start"); return; }
    setSubmitting(true);
    try { await onSubmit({ start_date: leaveStart, end_date: leaveEnd, leave_type: leaveType, reason }); reset(); onClose(); }
    catch (e: any) { Alert.alert("Error", e.message || "Failed to submit"); }
    finally { setSubmitting(false); }
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="formSheet" onDismiss={reset}>
      <SafeAreaView style={am.container}>
        <View style={am.header}>
          <TouchableOpacity onPress={() => { reset(); onClose(); }}>
            <Ionicons name="close" size={24} color={Colors.text} />
          </TouchableOpacity>
          <Text style={am.title}>Apply for Leave</Text>
          <View style={{ width: 24 }} />
        </View>

        <ScrollView contentContainerStyle={am.body} showsVerticalScrollIndicator={false}>
          {/* Leave Type */}
          <Text style={am.label}>Leave Type</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: Spacing.md }}>
            {LEAVE_TYPES.map(lt => {
              const bal   = getBal(lt);
              const active = leaveType === lt;
              const avail  = bal ? (bal.is_unlimited ? "∞" : `${bal.available_days.toFixed(1)}d`) : null;
              const low    = bal && !bal.is_unlimited && bal.available_days <= 0;
              return (
                <TouchableOpacity
                  key={lt}
                  style={[am.typeChip, active && am.typeChipActive, low && am.typeChipLow]}
                  onPress={() => onType(lt)}
                >
                  <Text style={[am.typeChipName, active && am.typeChipNameActive]}>
                    {lt.charAt(0).toUpperCase() + lt.slice(1)}
                  </Text>
                  {avail && (
                    <Text style={[am.typeChipBal, {
                      color: bal!.is_unlimited ? Colors.success
                        : low                  ? Colors.error
                        : bal!.available_days <= 2 ? Colors.warning
                        : Colors.success,
                    }]}>
                      {avail}
                    </Text>
                  )}
                </TouchableOpacity>
              );
            })}
          </ScrollView>

          {/* Balance banner */}
          {selBal && !selBal.is_unlimited && (
            <View style={[am.balBanner, selBal.available_days <= 0 ? am.bannerRed : selBal.available_days <= 2 ? am.bannerYellow : am.bannerGreen]}>
              <Text style={am.bannerText}>
                <Text style={{ fontWeight: "700", color: selBal.available_days <= 0 ? Colors.error : selBal.available_days <= 2 ? Colors.warning : Colors.success }}>
                  {selBal.available_days.toFixed(1)}
                </Text>
                {" "}available · {" "}
                <Text style={{ color: Colors.warning }}>{selBal.pending_days.toFixed(1)}</Text>
                {" "}pending · {" "}
                <Text style={{ color: Colors.error }}>{selBal.used_days.toFixed(1)}</Text>
                {" "}used
              </Text>
            </View>
          )}

          {/* Dates */}
          <View style={am.dateRow}>
            <View style={{ flex: 1 }}>
              <DateField
                label="Start Date"
                value={leaveStart}
                onChange={onStart}
                placeholder="YYYY-MM-DD"
                useOverlayInsideModal
              />
            </View>
            <View style={am.arrow}>
              <Ionicons name="arrow-forward" size={16} color={Colors.textTertiary} />
            </View>
            <View style={{ flex: 1 }}>
              <DateField
                label="End Date"
                value={leaveEnd}
                onChange={onEnd}
                placeholder="YYYY-MM-DD"
                useOverlayInsideModal
              />
            </View>
          </View>

          {/* Warnings */}
          {checking && (
            <View style={am.infoRow}>
              <ActivityIndicator size="small" color={Colors.textSecondary} />
              <Text style={am.infoText}>Checking holidays…</Text>
            </View>
          )}
          {!checking && holidayWarn && (
            <View style={am.warnBox}>
              <Ionicons name="information-circle-outline" size={15} color={Colors.warning} />
              <Text style={am.warnText}>{holidayWarn}</Text>
            </View>
          )}
          {balErr && (
            <View style={am.errBox}>
              <Ionicons name="alert-circle-outline" size={15} color={Colors.error} />
              <Text style={am.errText}>{balErr}</Text>
            </View>
          )}

          {/* Reason */}
          <Text style={am.label}>
            Reason {selBal?.requires_reason ? <Text style={{ color: Colors.error }}>*</Text> : "(optional)"}
          </Text>
          <TextInput
            style={[am.input, { height: 80, textAlignVertical: "top", paddingTop: 10 }]}
            value={reason}
            onChangeText={setReason}
            placeholder="Reason for leave…"
            placeholderTextColor={Colors.textTertiary}
            multiline
          />

          <TouchableOpacity
            style={[am.submitBtn, blocked && { opacity: 0.45 }]}
            onPress={handleSubmit}
            disabled={blocked}
          >
            {submitting
              ? <ActivityIndicator color="#fff" />
              : <Text style={am.submitText}>
                  {balErr ? "Insufficient Balance" : "Submit Request"}
                </Text>
            }
          </TouchableOpacity>
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

const am = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: Spacing.lg, paddingVertical: 14,
    borderBottomWidth: 1, borderBottomColor: Colors.borderLight,
  },
  title: { fontSize: 16, fontWeight: "700", color: Colors.text },
  body: { padding: Spacing.lg, paddingBottom: 40 },
  label: { fontSize: 12, fontWeight: "600", color: Colors.textSecondary, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: Spacing.sm, marginTop: Spacing.md },
  typeChip: {
    alignItems: "center", paddingHorizontal: 14, paddingVertical: 10,
    borderRadius: Layout.borderRadius.md, borderWidth: 1,
    borderColor: Colors.borderLight, backgroundColor: Colors.backgroundSecondary,
    marginRight: Spacing.sm, minWidth: 72, gap: 3,
  },
  typeChipActive: { borderColor: Colors.text, backgroundColor: Colors.text },
  typeChipLow: { borderColor: Colors.error + "60" },
  typeChipName: { fontSize: 13, fontWeight: "500", color: Colors.text },
  typeChipNameActive: { color: "#fff" },
  typeChipBal: { fontSize: 12, fontWeight: "700" },
  balBanner: {
    flexDirection: "row", alignItems: "center", padding: 10,
    borderRadius: Layout.borderRadius.sm, borderWidth: 1, marginBottom: 4,
  },
  bannerGreen:  { backgroundColor: Colors.success + "0D", borderColor: Colors.success + "40" },
  bannerYellow: { backgroundColor: Colors.warning + "0D", borderColor: Colors.warning + "40" },
  bannerRed:    { backgroundColor: Colors.error   + "0D", borderColor: Colors.error   + "40" },
  bannerText:   { fontSize: 12, color: Colors.text },
  dateRow: { flexDirection: "row", alignItems: "flex-end", gap: 6 },
  arrow: { paddingBottom: 11 },
  input: {
    borderWidth: 1, borderColor: Colors.border, borderRadius: Layout.borderRadius.sm,
    paddingHorizontal: 12, paddingVertical: 10,
    fontSize: 14, color: Colors.text, backgroundColor: Colors.backgroundSecondary,
  },
  infoRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: Spacing.sm },
  infoText: { fontSize: 12, color: Colors.textSecondary },
  warnBox: {
    flexDirection: "row", alignItems: "flex-start", gap: 6, marginTop: Spacing.sm,
    padding: 10, backgroundColor: Colors.warning + "0D",
    borderRadius: Layout.borderRadius.sm, borderWidth: 1, borderColor: Colors.warning + "40",
  },
  warnText: { flex: 1, fontSize: 12, color: Colors.text, lineHeight: 17 },
  errBox: {
    flexDirection: "row", alignItems: "flex-start", gap: 6, marginTop: Spacing.sm,
    padding: 10, backgroundColor: Colors.error + "0D",
    borderRadius: Layout.borderRadius.sm, borderWidth: 1, borderColor: Colors.error + "40",
  },
  errText: { flex: 1, fontSize: 12, color: Colors.error, lineHeight: 17 },
  submitBtn: {
    backgroundColor: Colors.primary, paddingVertical: 14,
    borderRadius: Layout.borderRadius.md, alignItems: "center", marginTop: Spacing.xl,
  },
  submitText: { color: "#fff", fontWeight: "700", fontSize: 15 },
});

// ---------------------------------------------------------------------------
// Main Screen
// ---------------------------------------------------------------------------
export default function LeaveTrackerScreen() {
  const { hasAnyPermission, permissions: rawPerms } = usePermissions();
  const canManageHolidays = hasAnyPermission([PERMS.HOLIDAY_MANAGE, PERMS.HOLIDAY_CREATE]);
  const canDeleteHolidays = hasAnyPermission([PERMS.HOLIDAY_MANAGE, PERMS.HOLIDAY_DELETE]);
  // Use raw permissions (not hierarchical) — admins have system.manage which would otherwise
  // expand to grant teacher.leave.apply, wrongly showing them the leave-application flow.
  const canApplyLeave = rawPerms.includes(PERMS.TEACHER_LEAVE_APPLY) &&
                        !rawPerms.includes(PERMS.SYSTEM_MANAGE) &&
                        !rawPerms.includes(PERMS.USER_MANAGE) &&
                        !rawPerms.includes(PERMS.TEACHER_LEAVE_MANAGE);

  const {
    leaves, loading, error,
    fetchMyLeaves, createLeave, cancelLeave,
    balances, balancesLoading, fetchMyBalances,
  } = useTeacherLeaves();

  const {
    holidays: hookHolidays,
    recurringHolidays: hookRecurring,
    loading: holLoading,
    fetchHolidays: hookFetchHolidays,
    fetchRecurring: hookFetchRecurring,
    createHoliday, updateHoliday, deleteHoliday,
  } = useHolidays();

  // Top-level: My Data  |  Holidays
  // Admins (holiday managers without leave.apply) land directly on Holidays
  const [topTab, setTopTab] = useState<"mydata" | "holidays">(canApplyLeave ? "mydata" : "holidays");
  useEffect(() => { if (!canApplyLeave) setTopTab("holidays"); }, [canApplyLeave]);

  // My Data sub-tab
  const [dataTab, setDataTab] = useState<DataTab>("Summary");

  // Requests filter
  const [statusFilter, setStatusFilter] = useState("");

  // Holidays
  const [holYear, setHolYear] = useState(new Date().getFullYear());
  const [holModalVisible, setHolModalVisible] = useState(false);
  const [holEditTarget, setHolEditTarget] = useState<Holiday | null>(null);

  // Combine + filter weekly_off for display
  const holidays = [...hookHolidays, ...hookRecurring].filter(h => h.holiday_type !== 'weekly_off');

  // Modals
  const [showApply,     setShowApply]     = useState(false);
  const [selectedBal,   setSelectedBal]   = useState<LeaveBalance | null>(null);

  // Animated sub-tab indicator
  const tabInd = useRef(new Animated.Value(0)).current;
  const tabW   = SW / DATA_TABS.length;

  const switchDataTab = (t: DataTab) => {
    Animated.spring(tabInd, { toValue: DATA_TABS.indexOf(t) * tabW, useNativeDriver: true, bounciness: 3 }).start();
    setDataTab(t);
  };

  // ── Loaders ──
  const loadLeaves = useCallback((f?: string) => fetchMyLeaves(f ? { status: f } : undefined), [fetchMyLeaves]);

  useEffect(() => { if (canApplyLeave) loadLeaves(statusFilter); }, [statusFilter, canApplyLeave]);
  useEffect(() => { if (canApplyLeave) fetchMyBalances(); }, [canApplyLeave]);

  const loadHolidays = useCallback((year: number) => {
    hookFetchHolidays({ start_date: `${year}-01-01`, end_date: `${year}-12-31` });
    hookFetchRecurring();
  }, [hookFetchHolidays, hookFetchRecurring]);

  useEffect(() => { if (topTab === "holidays") loadHolidays(holYear); }, [topTab, holYear]);

  const handleHolSubmit = async (data: CreateHolidayDTO) => {
    try {
      if (holEditTarget) {
        const updated = await updateHoliday(holEditTarget.id, data);
        if ((updated as any).warning) Alert.alert("Holiday Updated", (updated as any).warning);
      } else {
        const created = await createHoliday(data);
        if ((created as any).warning) Alert.alert("Holiday Added", (created as any).warning);
      }
      setHolModalVisible(false);
    } catch (err: any) { throw err; }
  };

  const handleHolDelete = (h: Holiday) => {
    Alert.alert(
      "Delete Holiday",
      `Remove "${h.name}"?`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: async () => {
            try { await deleteHoliday(h.id, h.is_recurring); }
            catch (err: any) { Alert.alert("Error", err.message || "Failed to delete"); }
          },
        },
      ]
    );
  };

  const handleCancel = (leave: TeacherLeave) => {
    Alert.alert("Cancel Leave", "Cancel this leave request?", [
      { text: "No", style: "cancel" },
      {
        text: "Yes, Cancel", style: "destructive",
        onPress: async () => {
          try { await cancelLeave(leave.id); await fetchMyBalances(); }
          catch (e: any) { Alert.alert("Error", e.message || "Failed to cancel"); }
        },
      },
    ]);
  };

  const handleSubmit = async (dto: any) => {
    const result = await createLeave(dto);
    await fetchMyBalances();
    const warn = (result as any)?.warning;
    if (warn) setTimeout(() => Alert.alert("Applied", warn), 350);
  };

  const filtered      = statusFilter ? leaves.filter(l => l.status === statusFilter) : leaves;
  const pendingCount  = leaves.filter(l => l.status === "pending").length;
  const approvedCount = leaves.filter(l => l.status === "approved").length;
  const rejectedCount = leaves.filter(l => l.status === "rejected").length;
  const recentLeaves  = leaves.slice(0, 10);

  // ── Year nav label ──
  const holYearLabel = `01 Jan ${holYear}  –  31 Dec ${holYear}`;

  return (
    <SafeAreaView style={s.container}>

      {/* ══ HEADER ══ */}
      <View style={s.header}>
        <Text style={s.headerTitle}>Leave Tracker</Text>
        {topTab === "holidays" && canManageHolidays ? (
          <TouchableOpacity style={s.applyBtn} onPress={() => { setHolEditTarget(null); setHolModalVisible(true); }}>
            <Ionicons name="add" size={18} color="#fff" />
            <Text style={s.applyBtnText}>Add Holiday</Text>
          </TouchableOpacity>
        ) : canApplyLeave ? (
          <TouchableOpacity style={s.applyBtn} onPress={() => setShowApply(true)}>
            <Ionicons name="add" size={18} color="#fff" />
            <Text style={s.applyBtnText}>Apply</Text>
          </TouchableOpacity>
        ) : null}
      </View>

      {/* ══ TOP TOGGLE  My Data | Holidays ══ */}
      {/* Only show the toggle if the user can also apply leave; otherwise only Holidays tab is relevant */}
      {canApplyLeave && (
        <View style={s.topToggleRow}>
          <TouchableOpacity
            style={[s.toggleBtn, topTab === "mydata" && s.toggleBtnActive]}
            onPress={() => setTopTab("mydata")}
          >
            <Text style={[s.toggleBtnText, topTab === "mydata" && s.toggleBtnTextActive]}>
              My Data
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[s.toggleBtn, topTab === "holidays" && s.toggleBtnActive]}
            onPress={() => setTopTab("holidays")}
          >
            <Text style={[s.toggleBtnText, topTab === "holidays" && s.toggleBtnTextActive]}>
              Holidays
            </Text>
          </TouchableOpacity>
        </View>
      )}

      {/* ══ MY DATA ══ */}
      {topTab === "mydata" && (
        <View style={{ flex: 1 }}>

          {/* Sub-tabs */}
          <View style={s.subTabBar}>
            {DATA_TABS.map(t => (
              <TouchableOpacity
                key={t}
                style={[s.subTab, { width: tabW }]}
                onPress={() => switchDataTab(t)}
              >
                <Text style={[s.subTabText, dataTab === t && s.subTabTextActive]}>
                  {t}
                  {t === "Requests" && pendingCount > 0
                    ? <Text style={s.pendingBadge}> {pendingCount}</Text>
                    : null}
                </Text>
              </TouchableOpacity>
            ))}
            <Animated.View style={[s.subTabLine, { width: tabW, transform: [{ translateX: tabInd }] }]} />
          </View>

          {/* ─ Summary ─ */}
          {dataTab === "Summary" && (
            <ScrollView
              showsVerticalScrollIndicator={false}
              refreshControl={
                <RefreshControl refreshing={loading || balancesLoading} onRefresh={() => { loadLeaves(); fetchMyBalances(); }} colors={[Colors.primary]} tintColor={Colors.primary} />
              }
            >
              {/* Quick stats */}
              <View style={s.statsCard}>
                <View style={s.statCol}>
                  <Text style={[s.statNum, { color: Colors.success }]}>{approvedCount}</Text>
                  <Text style={s.statLabel}>Approved</Text>
                </View>
                <View style={s.statSep} />
                <View style={s.statCol}>
                  <Text style={[s.statNum, { color: Colors.warning }]}>{pendingCount}</Text>
                  <Text style={s.statLabel}>Pending</Text>
                </View>
                <View style={s.statSep} />
                <View style={s.statCol}>
                  <Text style={[s.statNum, { color: Colors.error }]}>{rejectedCount}</Text>
                  <Text style={s.statLabel}>Rejected</Text>
                </View>
              </View>

              {/* Balance cards */}
              {balancesLoading ? (
                <View style={s.loadRow}>
                  <ActivityIndicator size="small" color={Colors.textSecondary} />
                  <Text style={s.loadText}>Loading balance…</Text>
                </View>
              ) : balances.length > 0 ? (
                <View>
                  <Text style={s.sectionTitle}>Leave Balance</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.cardScrollPad}>
                    {balances.map(b => (
                      <BalanceCard key={b.leave_type} balance={b} onPress={() => setSelectedBal(b)} />
                    ))}
                  </ScrollView>
                </View>
              ) : null}

              {/* Recent requests */}
              <Text style={s.sectionTitle}>Recent Requests</Text>
              {recentLeaves.length === 0 && !loading ? (
                <View style={s.emptyBlock}>
                  <Ionicons name="document-text-outline" size={42} color={Colors.borderLight} />
                  <Text style={s.emptyText}>No leave requests yet</Text>
                  <TouchableOpacity style={s.emptyApplyBtn} onPress={() => setShowApply(true)}>
                    <Text style={s.emptyApplyText}>Apply for Leave</Text>
                  </TouchableOpacity>
                </View>
              ) : (
                recentLeaves.map(item => (
                  <LeaveRow key={item.id} item={item}
                    onCancel={item.status === "pending" ? () => handleCancel(item) : undefined}
                  />
                ))
              )}
              <View style={{ height: 80 }} />
            </ScrollView>
          )}

          {/* ─ Balance ─ */}
          {dataTab === "Balance" && (
            <ScrollView
              showsVerticalScrollIndicator={false}
              refreshControl={<RefreshControl refreshing={balancesLoading} onRefresh={fetchMyBalances} colors={[Colors.primary]} tintColor={Colors.primary} />}
            >
              {balancesLoading ? (
                <View style={s.center}><ActivityIndicator color={Colors.primary} /></View>
              ) : balances.length === 0 ? (
                <View style={s.center}>
                  <Ionicons name="wallet-outline" size={44} color={Colors.borderLight} />
                  <Text style={s.emptyText}>No balance data</Text>
                </View>
              ) : (
                <>
                  <View style={s.balHeader}>
                    <Text style={s.balHeaderTitle}>Annual Leave Allocation</Text>
                    <Text style={s.balHeaderSub}>Academic Year {balances[0]?.academic_year ?? "—"}</Text>
                  </View>
                  {balances.map(b => <BalanceDetailRow key={b.leave_type} b={b} />)}
                  <View style={{ height: 80 }} />
                </>
              )}
            </ScrollView>
          )}

          {/* ─ Requests ─ */}
          {dataTab === "Requests" && (
            <View style={{ flex: 1 }}>
              {/* Filter chips */}
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.filterBar} contentContainerStyle={s.filterBarPad}>
                {STATUS_FILTERS.map(f => (
                  <TouchableOpacity
                    key={f.value}
                    style={[s.chip, statusFilter === f.value && s.chipActive]}
                    onPress={() => setStatusFilter(f.value)}
                  >
                    <Text style={[s.chipText, statusFilter === f.value && s.chipTextActive]}>{f.label}</Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>

              {error ? (
                <View style={s.center}>
                  <Ionicons name="alert-circle-outline" size={42} color={Colors.error} />
                  <Text style={s.emptyText}>{error}</Text>
                  <TouchableOpacity style={s.retryBtn} onPress={() => loadLeaves(statusFilter)}>
                    <Text style={s.retryBtnText}>Retry</Text>
                  </TouchableOpacity>
                </View>
              ) : (
                <FlatList
                  data={filtered}
                  keyExtractor={i => i.id}
                  renderItem={({ item }) => (
                    <LeaveRow item={item}
                      onCancel={item.status === "pending" ? () => handleCancel(item) : undefined}
                    />
                  )}
                  refreshControl={<RefreshControl refreshing={loading} onRefresh={() => loadLeaves(statusFilter)} colors={[Colors.primary]} tintColor={Colors.primary} />}
                  contentContainerStyle={filtered.length === 0 ? s.emptyContainer : undefined}
                  ListEmptyComponent={
                    !loading ? (
                      <View style={s.center}>
                        <Ionicons name="document-text-outline" size={48} color={Colors.borderLight} />
                        <Text style={s.emptyText}>No {statusFilter || ""} leave requests</Text>
                      </View>
                    ) : null
                  }
                />
              )}
            </View>
          )}
        </View>
      )}

      {/* ══ HOLIDAYS ══ */}
      {topTab === "holidays" && (
        <View style={{ flex: 1 }}>
          {/* Year navigator */}
          <View style={s.yearNav}>
            <TouchableOpacity onPress={() => setHolYear(y => y - 1)} style={s.yearArrow}>
              <Ionicons name="chevron-back" size={20} color={Colors.text} />
            </TouchableOpacity>
            <Text style={s.yearLabel}>{holYearLabel}</Text>
            <TouchableOpacity onPress={() => setHolYear(y => y + 1)} style={s.yearArrow}>
              <Ionicons name="chevron-forward" size={20} color={Colors.text} />
            </TouchableOpacity>
          </View>

          {holLoading ? (
            <View style={s.center}><ActivityIndicator color={Colors.primary} /></View>
          ) : (
            <FlatList
              data={holidays}
              keyExtractor={h => h.id}
              renderItem={({ item }) => (
                <HolidayRow
                  h={item}
                  onEdit={canManageHolidays ? (h) => { setHolEditTarget(h); setHolModalVisible(true); } : undefined}
                  onDelete={canDeleteHolidays ? handleHolDelete : undefined}
                />
              )}
              refreshControl={<RefreshControl refreshing={holLoading} onRefresh={() => loadHolidays(holYear)} colors={[Colors.primary]} tintColor={Colors.primary} />}
              contentContainerStyle={holidays.length === 0 ? s.emptyContainer : { paddingBottom: 80 }}
              ListEmptyComponent={
                <View style={s.center}>
                  <Ionicons name="calendar-outline" size={48} color={Colors.borderLight} />
                  <Text style={s.emptyText}>No holidays for {holYear}</Text>
                  {canManageHolidays && (
                    <TouchableOpacity style={s.emptyApplyBtn} onPress={() => { setHolEditTarget(null); setHolModalVisible(true); }}>
                      <Text style={s.emptyApplyText}>Add Holiday</Text>
                    </TouchableOpacity>
                  )}
                </View>
              }
            />
          )}
        </View>
      )}

      {/* ══ FAB ══ */}
      {topTab === "holidays" ? (
        canManageHolidays ? (
          <TouchableOpacity style={s.fab} onPress={() => { setHolEditTarget(null); setHolModalVisible(true); }} activeOpacity={0.85}>
            <Ionicons name="add" size={28} color="#fff" />
          </TouchableOpacity>
        ) : null
      ) : canApplyLeave ? (
        <TouchableOpacity style={s.fab} onPress={() => setShowApply(true)} activeOpacity={0.85}>
          <Ionicons name="add" size={28} color="#fff" />
        </TouchableOpacity>
      ) : null}

      {/* ══ HOLIDAY FORM MODAL ══ */}
      <HolidayFormModal
        visible={holModalVisible}
        onClose={() => setHolModalVisible(false)}
        onSubmit={handleHolSubmit}
        initialData={holEditTarget}
        mode={holEditTarget ? "edit" : "create"}
      />

      {/* ══ APPLY MODAL ══ */}
      <ApplyModal
        visible={showApply}
        balances={balances}
        onClose={() => setShowApply(false)}
        onSubmit={handleSubmit}
      />

      {/* ══ BALANCE DETAIL SHEET ══ */}
      <Modal
        visible={!!selectedBal}
        animationType="slide"
        transparent
        onDismiss={() => setSelectedBal(null)}
      >
        <View style={s.bsOverlay}>
          <TouchableOpacity style={{ flex: 1 }} activeOpacity={1} onPress={() => setSelectedBal(null)} />
          {selectedBal && (
            <View style={s.bsSheet}>
              <View style={s.bsHandle} />
              <Text style={s.bsTitle}>
                {selectedBal.leave_type.charAt(0).toUpperCase() + selectedBal.leave_type.slice(1)} Leave
              </Text>
              <Text style={s.bsSub}>{selectedBal.academic_year}</Text>

              {selectedBal.is_unlimited ? (
                <View style={s.bsRow}>
                  <Text style={s.bsRowLabel}>Balance</Text>
                  <Text style={[s.bsRowVal, { color: Colors.success }]}>Unlimited</Text>
                </View>
              ) : (
                <>
                  {[
                    { label: "Balance",       val: selectedBal.available_days.toFixed(1), color: selectedBal.available_days <= 0 ? Colors.error : selectedBal.available_days <= 2 ? Colors.warning : Colors.success },
                    { label: "Booked",        val: selectedBal.pending_days.toFixed(1),   color: Colors.warning },
                    { label: "Used",          val: selectedBal.used_days.toFixed(1),      color: Colors.error },
                    { label: "Total",         val: `${selectedBal.allocated_days + selectedBal.carried_forward_days}`, color: Colors.text },
                  ].map(row => (
                    <View key={row.label} style={s.bsRow}>
                      <Text style={s.bsRowLabel}>{row.label}</Text>
                      <Text style={[s.bsRowVal, { color: row.color }]}>{row.val}</Text>
                    </View>
                  ))}
                  {selectedBal.carried_forward_days > 0 && (
                    <View style={s.bsRow}>
                      <Text style={s.bsRowLabel}>Carried Forward</Text>
                      <Text style={[s.bsRowVal, { color: Colors.textSecondary }]}>+{selectedBal.carried_forward_days}</Text>
                    </View>
                  )}
                </>
              )}

              <TouchableOpacity
                style={s.bsApplyBtn}
                onPress={() => { setSelectedBal(null); setTimeout(() => setShowApply(true), 250); }}
              >
                <Text style={s.bsApplyBtnText}>Apply Leave</Text>
              </TouchableOpacity>
            </View>
          )}
        </View>
      </Modal>

    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const s = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },

  // Header
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: Spacing.md, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: Colors.borderLight,
  },
  headerTitle: { flex: 1, fontSize: 20, fontWeight: "700", color: Colors.text },
  applyBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: Colors.primary, paddingHorizontal: 14, paddingVertical: 7,
    borderRadius: 20,
  },
  applyBtnText: { color: "#fff", fontWeight: "600", fontSize: 13 },

  // Top toggle
  topToggleRow: {
    flexDirection: "row", gap: Spacing.sm,
    paddingHorizontal: Spacing.lg, paddingVertical: Spacing.md,
    borderBottomWidth: 1, borderBottomColor: Colors.borderLight,
  },
  toggleBtn: {
    paddingHorizontal: Spacing.lg, paddingVertical: 8,
    borderRadius: 20, borderWidth: 1, borderColor: Colors.borderLight,
    backgroundColor: Colors.backgroundSecondary,
  },
  toggleBtnActive: { backgroundColor: Colors.primary, borderColor: Colors.primary },
  toggleBtnText:   { fontSize: 14, fontWeight: "600", color: Colors.textSecondary },
  toggleBtnTextActive: { color: "#fff" },

  // Sub-tabs
  subTabBar: {
    flexDirection: "row", borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight, position: "relative",
  },
  subTab: { paddingVertical: 12, alignItems: "center" },
  subTabText: { fontSize: 13, fontWeight: "500", color: Colors.textSecondary },
  subTabTextActive: { color: Colors.text, fontWeight: "700" },
  pendingBadge: { color: Colors.warning, fontWeight: "700" },
  subTabLine: {
    height: 2, backgroundColor: Colors.primary, borderRadius: 1,
    position: "absolute", bottom: 0, left: 0,
  },

  // Summary stats
  statsCard: {
    flexDirection: "row", marginHorizontal: Spacing.lg, marginTop: Spacing.md,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.md, borderWidth: 1, borderColor: Colors.borderLight,
    overflow: "hidden",
  },
  statCol: { flex: 1, alignItems: "center", paddingVertical: Spacing.md },
  statSep: { width: 1, backgroundColor: Colors.borderLight },
  statNum: { fontSize: 22, fontWeight: "800" },
  statLabel: { fontSize: 11, color: Colors.textTertiary, marginTop: 2 },

  sectionTitle: {
    fontSize: 12, fontWeight: "700", color: Colors.textSecondary,
    textTransform: "uppercase", letterSpacing: 0.5,
    paddingHorizontal: Spacing.lg, marginTop: Spacing.lg, marginBottom: Spacing.sm,
  },
  cardScrollPad: { paddingHorizontal: Spacing.lg, paddingBottom: Spacing.sm },

  loadRow: { flexDirection: "row", alignItems: "center", gap: Spacing.sm, padding: Spacing.lg },
  loadText: { fontSize: 13, color: Colors.textSecondary },

  // Balance tab header
  balHeader: {
    paddingHorizontal: Spacing.lg, paddingVertical: Spacing.md,
    borderBottomWidth: 1, borderBottomColor: Colors.borderLight,
    backgroundColor: Colors.backgroundSecondary,
  },
  balHeaderTitle: { fontSize: 15, fontWeight: "700", color: Colors.text },
  balHeaderSub:   { fontSize: 12, color: Colors.textSecondary, marginTop: 2 },

  // Filter chips
  filterBar: { flexGrow: 0, borderBottomWidth: 1, borderBottomColor: Colors.borderLight },
  filterBarPad: { paddingHorizontal: Spacing.md, paddingVertical: Spacing.sm, alignItems: "center" },
  chip: {
    paddingHorizontal: 14, paddingVertical: 6, borderRadius: 16,
    borderWidth: 1, borderColor: Colors.borderLight,
    backgroundColor: Colors.backgroundSecondary, marginRight: Spacing.sm,
  },
  chipActive: { backgroundColor: Colors.primary, borderColor: Colors.primary },
  chipText: { fontSize: 13, color: Colors.textSecondary, fontWeight: "500" },
  chipTextActive: { color: "#fff", fontWeight: "600" },

  // Year nav
  yearNav: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: Spacing.md, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: Colors.borderLight,
  },
  yearArrow: { padding: 8 },
  yearLabel: { fontSize: 14, fontWeight: "600", color: Colors.text },

  // Shared
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: Spacing.xl },
  emptyContainer: { flex: 1, justifyContent: "center", alignItems: "center", padding: Spacing.xl },
  emptyBlock: { alignItems: "center", paddingVertical: Spacing.xl },
  emptyText: { fontSize: 14, color: Colors.textSecondary, marginTop: Spacing.sm, textAlign: "center" },
  emptyApplyBtn: { marginTop: Spacing.md, backgroundColor: Colors.primary, paddingHorizontal: Spacing.xl, paddingVertical: Spacing.sm, borderRadius: 20 },
  emptyApplyText: { color: "#fff", fontWeight: "600", fontSize: 14 },
  retryBtn: { marginTop: Spacing.md, backgroundColor: Colors.primary, paddingHorizontal: Spacing.xl, paddingVertical: Spacing.sm, borderRadius: Layout.borderRadius.sm },
  retryBtnText: { color: "#fff", fontWeight: "600" },

  // FAB
  fab: {
    position: "absolute", right: Spacing.lg, bottom: Spacing.lg + 8,
    width: 54, height: 54, borderRadius: 27,
    backgroundColor: Colors.primary,
    justifyContent: "center", alignItems: "center",
    shadowColor: "#000", shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.2, shadowRadius: 8, elevation: 6,
  },

  // Bottom sheet
  bsOverlay: { flex: 1, backgroundColor: Colors.overlay, justifyContent: "flex-end" },
  bsSheet: {
    backgroundColor: Colors.background,
    borderTopLeftRadius: Layout.borderRadius.xl,
    borderTopRightRadius: Layout.borderRadius.xl,
    paddingHorizontal: Spacing.lg, paddingBottom: Spacing.xl,
  },
  bsHandle: {
    width: 40, height: 4, borderRadius: 2, backgroundColor: Colors.borderLight,
    alignSelf: "center", marginTop: Spacing.sm, marginBottom: Spacing.md,
  },
  bsTitle: { fontSize: 18, fontWeight: "700", color: Colors.text },
  bsSub: { fontSize: 13, color: Colors.textSecondary, marginBottom: Spacing.md, marginTop: 2 },
  bsRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: Colors.borderLight,
  },
  bsRowLabel: { fontSize: 15, color: Colors.textSecondary },
  bsRowVal: { fontSize: 18, fontWeight: "800" },
  bsApplyBtn: {
    marginTop: Spacing.lg, backgroundColor: Colors.primary,
    paddingVertical: 14, borderRadius: Layout.borderRadius.lg, alignItems: "center",
  },
  bsApplyBtnText: { color: "#fff", fontWeight: "700", fontSize: 16 },
});
