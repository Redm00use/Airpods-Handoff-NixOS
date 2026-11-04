const std = @import("std");

const frame_prefix = [_]u8{ 0x04, 0x00, 0x04, 0x00 };
const opcode_offset = frame_prefix.len;
const address_offset = opcode_offset + @sizeOf(u16);
const payload_length_offset = address_offset + 6;
const metadata_offset = payload_length_offset + @sizeOf(u16);
const payload_offset = metadata_offset + 1;
const max_packet_size = 1024;

pub const Address = [6]u8;
pub const max_payload_size = max_packet_size - payload_offset;

pub const Opcode = enum(u16) {
    send = 0x0010,
    receive = 0x0011,

    pub fn name(self: Opcode) []const u8 {
        return switch (self) {
            .send => "send",
            .receive => "receive",
        };
    }
};

pub const Message = struct {
    opcode: Opcode,
    // Preserve wire order until a Mac capture proves how the relay identifies its peer.
    address: Address,
    metadata: u8,
    // The slice borrows the AACP receive buffer and remains valid only until the next receive.
    payload: []const u8,
};

pub const Frame = struct {
    bytes: [max_packet_size]u8 = undefined,
    len: usize,

    pub fn packet(self: *const Frame) []const u8 {
        return self.bytes[0..self.len];
    }
};

// Return null for unrelated traffic and an error only after the frame identifies a relay opcode.
pub fn parse(packet: []const u8) error{InvalidRelayPacket}!?Message {
    if (packet.len < frame_prefix.len or !std.mem.eql(u8, packet[0..frame_prefix.len], &frame_prefix)) {
        return null;
    }
    if (packet.len < address_offset) return error.InvalidRelayPacket;

    const opcode: Opcode = switch (std.mem.readInt(u16, packet[opcode_offset..address_offset], .little)) {
        @intFromEnum(Opcode.send) => .send,
        @intFromEnum(Opcode.receive) => .receive,
        else => return null,
    };
    if (packet.len < payload_offset) return error.InvalidRelayPacket;

    const payload_length = std.mem.readInt(
        u16,
        packet[payload_length_offset..metadata_offset],
        .little,
    );
    if (payload_length > max_payload_size + 1 or payload_length == 0 or packet.len != metadata_offset + payload_length) {
        return error.InvalidRelayPacket;
    }

    return .{
        .opcode = opcode,
        .address = packet[address_offset..payload_length_offset].*,
        .metadata = packet[metadata_offset],
        .payload = packet[payload_offset..],
    };
}

pub fn encode(
    opcode: Opcode,
    address: Address,
    metadata: u8,
    payload: []const u8,
) error{RelayPayloadTooLarge}!Frame {
    if (payload.len > max_payload_size) return error.RelayPayloadTooLarge;

    var frame = Frame{ .len = payload_offset + payload.len };
    @memcpy(frame.bytes[0..frame_prefix.len], &frame_prefix);
    std.mem.writeInt(u16, frame.bytes[opcode_offset..address_offset], @intFromEnum(opcode), .little);
    @memcpy(frame.bytes[address_offset..payload_length_offset], &address);
    std.mem.writeInt(u16, frame.bytes[payload_length_offset..metadata_offset], @intCast(payload.len + 1), .little);
    frame.bytes[metadata_offset] = metadata;
    @memcpy(frame.bytes[payload_offset..frame.len], payload);
    return frame;
}

// Minimal bounded OPACK reader for a flat routing request. Unknown types,
// malformed references, duplicate decision keys and trailing data fail closed.
const Atom = union(enum) {
    string: []const u8,
    integer: u64,
    flag: bool,

    fn equal(a: Atom, b: Atom) bool {
        return switch (a) {
            .string => |v| b == .string and std.mem.eql(u8, v, b.string),
            .integer => |v| b == .integer and v == b.integer,
            .flag => |v| b == .flag and v == b.flag,
        };
    }
};

const Opack = struct {
    data: []const u8,
    pos: usize = 0,
    refs: [32]Atom = undefined,
    count: usize = 0,

    fn take(self: *Opack, n: usize) error{InvalidOpack}![]const u8 {
        if (n > self.data.len - self.pos) return error.InvalidOpack;
        const value = self.data[self.pos..][0..n];
        self.pos += n;
        return value;
    }

    fn remember(self: *Opack, value: Atom) error{InvalidOpack}!Atom {
        for (self.refs[0..self.count]) |old| if (old.equal(value)) return value;
        if (self.count == self.refs.len) return error.InvalidOpack;
        self.refs[self.count] = value;
        self.count += 1;
        return value;
    }

    fn number(self: *Opack, n: usize) error{InvalidOpack}!u64 {
        var value: u64 = 0;
        for (try self.take(n), 0..) |byte, i| value |= @as(u64, byte) << @as(u6, @intCast(i * 8));
        return value;
    }

    fn atom(self: *Opack) error{InvalidOpack}!Atom {
        const tag = (try self.take(1))[0];
        if (tag == 1 or tag == 2) return .{ .flag = tag == 1 };
        if (tag >= 8 and tag <= 0x2f) return .{ .integer = tag - 8 };
        if (tag >= 0x30 and tag <= 0x33) return self.remember(.{ .integer = try self.number(@as(usize, 1) << @as(u6, @intCast(tag - 0x30))) });
        if (tag >= 0x40 and tag <= 0x60) return self.remember(.{ .string = try self.take(tag - 0x40) });
        if (tag >= 0x61 and tag <= 0x63) {
            const length = try self.number(@as(usize, 1) << @as(u6, @intCast(tag - 0x61)));
            if (length > max_payload_size) return error.InvalidOpack;
            return self.remember(.{ .string = try self.take(@intCast(length)) });
        }
        if (tag >= 0xa0 and tag <= 0xc0 and tag - 0xa0 < self.count) return self.refs[tag - 0xa0];
        return error.InvalidOpack;
    }

    fn routingRequest(self: *Opack, scored: bool) error{InvalidOpack}!bool {
        const tag = (try self.take(1))[0];
        if (tag < 0xe0 or tag > 0xee) return error.InvalidOpack;
        var owns_seen = false;
        var reason_seen = false;
        var yield = false;
        var reason_matches = false;
        var score_seen = false;
        var score_required = false;
        for (0..tag - 0xe0) |_| {
            const key = try self.atom();
            const value = try self.atom();
            if (key != .string) return error.InvalidOpack;
            if (std.mem.eql(u8, key.string, "audioRoutingSetOwnershipToFalse")) {
                if (owns_seen or value != .flag) return error.InvalidOpack;
                owns_seen = true;
                yield = value.flag;
            } else if (std.mem.eql(u8, key.string, "reason")) {
                if (reason_seen or value != .string) return error.InvalidOpack;
                reason_seen = true;
                if (scored) {
                    score_required = std.mem.eql(u8, value.string, "Hijackv2");
                    reason_matches = score_required or std.mem.eql(u8, value.string, "RoutedToBluetooth");
                } else {
                    reason_matches = std.mem.eql(u8, value.string, "ManualRoute") or std.mem.eql(u8, value.string, "ReverseBannerTapped");
                }
            } else if (std.mem.eql(u8, key.string, "audioRoutingScore")) {
                if (score_seen or value != .integer) return error.InvalidOpack;
                score_seen = true;
            }
        }
        if (self.pos != self.data.len) return error.InvalidOpack;
        return owns_seen and reason_seen and yield and reason_matches and (!score_required or score_seen);
    }
};

pub fn isManualRouteRequest(packet: []const u8) bool {
    const message = (parse(packet) catch return false) orelse return false;
    if (message.opcode != .receive or message.metadata != 1) return false;
    var reader = Opack{ .data = message.payload };
    return reader.routingRequest(false) catch false;
}

pub fn automaticRequest(packet: []const u8) ?Message {
    const message = (parse(packet) catch return null) orelse return null;
    if (message.opcode != .receive or message.metadata != 1) return null;
    var reader = Opack{ .data = message.payload };
    if (!(reader.routingRequest(true) catch false)) return null;
    return message;
}
