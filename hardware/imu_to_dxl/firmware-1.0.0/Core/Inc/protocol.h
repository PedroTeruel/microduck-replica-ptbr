#ifndef IMU_TO_DXL_PROTOCOL_H
#define IMU_TO_DXL_PROTOCOL_H

#include <stdint.h>

/* Feetech FT-SCS one-wire half-duplex slave, sharing the 1 Mbit/s bus with
 * Feetech servos. This board is NOT a Robotis device and speaks no DXL2.
 *
 * Wire frame:
 *   FF FF ID LEN INST P_1..P_n CK     (request)
 *   FF FF ID LEN ERR D_1..D_d CK      (status, same framing)
 * LEN counts INST(ERR) + parameters(data) + CK = n + 2. Every frame totals
 * 4 + LEN bytes. Checksum = ~(ID + LEN + INST/ERR + sum(params/data)) & 0xFF.
 *
 * Supported instructions (broadcast ID = 0xFE):
 *   0x01 PING        unicast only; empty status reply
 *   0x02 READ        (addr u8, count u8) unicast; status + data
 *   0x03 WRITE       (addr u8, data...); unicast ACK, broadcast silent
 *   0x82 SYNC READ   (addr, count, id...) to broadcast; ordered status replies
 *   0x83 SYNC WRITE  (addr, dlen, [id, data]...) to broadcast; silent
 * Unknown instructions stay silent. No Reg Write, Reset, or flash writes.
 *
 * Register map (per hardware/imu_to_dxl/总线协议.md):
 *   0..9 protocol-owned identity:
 *     0-1 firmware version (major, minor), 2 endian (0=little),
 *     3-4 model (0x4D44), 5 ID=200, 6 baud=0, 8 status level=1
 *   56..70 15-byte fast block: gyro i16 x3 (17.5 mdps/LSB) + SFLP qx/qy/qz
 *     fp16 + sample counter u8 + status bits u8 + reserved u8 (0). Same address
 *     as Feetech servo status block, so one SYNC READ 56/15 gets this board
 *     and every servo. Host reconstructs quaternion w.
 *   90..185 diagnostics (24 little-endian u32). */
#define PROTO_DEVICE_ID             200u
#define PROTO_MODEL_NUMBER          0x4D44u
#define PROTO_FIRMWARE_MAJOR        1u
#define PROTO_FIRMWARE_MINOR        0u
#define PROTO_ENDIAN                0u /* 0 = little-endian; servo-web asserts. */
#define PROTO_STATUS_LEVEL          1u
#define PROTO_BAUD_CODE             0u /* Feetech/SMS code 0 = 1,000,000 bit/s. */
#define PROTO_PACKET_CAPACITY       512u
#define PROTO_MAX_READ              128u
/* Largest sane LEN byte: READ status with 128 data bytes is LEN 130; a single
 * segment SYNC WRITE of 128 data bytes is LEN 132. Anything bigger is noise and
 * must be rejected immediately rather than swallowing the following packets. */
#define PROTO_MAX_FRAME_LEN         132u
#define PROTO_BYTE_TIMEOUT_US       1500u
#define PROTO_TRANSACTION_TIMEOUT_US 25000u
#define PROTO_REPLY_EXPIRY_US       2000u

enum {
    PROTO_OK = 0,
    PROTO_ERR_RESULT = 1,
    PROTO_ERR_INSTRUCTION = 2,
    PROTO_ERR_CRC = 3,
    PROTO_ERR_RANGE = 4,
    PROTO_ERR_LENGTH = 5,
    PROTO_ERR_LIMIT = 6,
    PROTO_ERR_ACCESS = 7
};

/* Callbacks return a protocol error code. read must fill the complete requested
 * range atomically; write must validate the WHOLE range before changing data.
 * Protocol-owned addresses: 0..9 (identity). Application read callbacks may
 * receive subranges around these addresses. Application write callbacks never
 * receive a range touching owned addresses.
 * send is synchronous: send every byte, wait for UART TC (not TXE), release
 * the driver, re-enable RX, then return. No callbacks run in an ISR. */
typedef uint8_t (*proto_read_fn)(void *user, uint16_t address,
                              uint16_t length, uint8_t *out);
typedef uint8_t (*proto_write_fn)(void *user, uint16_t address,
                               uint16_t length, const uint8_t *data);
typedef void (*proto_send_fn)(void *user, const uint8_t *packet, uint16_t length);

typedef struct {
    uint8_t rx[PROTO_PACKET_CAPACITY];
    uint8_t tx[PROTO_PACKET_CAPACITY];
    proto_read_fn read;
    proto_write_fn write;
    proto_send_fn send;
    void *user;
    uint32_t last_byte_us;
    uint32_t transaction_start_us;
    uint32_t reply_due_us;
    uint32_t rx_packets;
    uint32_t tx_packets;
    uint32_t checksum_errors;
    uint32_t malformed_packets;
    uint32_t receive_timeouts;
    uint32_t cancelled_replies;
    uint16_t rx_length;
    uint16_t rx_expected;
    uint16_t tx_length;
    uint8_t pending;             /* 0 none, 1 ready/due, 2 preceding ID */
    uint8_t preceding_id;
} proto_context;

void proto_init(proto_context *ctx, proto_read_fn read_registers,
                proto_write_fn write_registers, proto_send_fn send, void *user);
/* Unsigned 32-bit MICROSECOND timestamps; wraparound is supported. Pass the
 * actual receive timestamp when draining an ISR ring, not the later drain time.
 * Drain RX before proto_poll, and poll frequently (target <100 us).
 * SYNC READ needs ordered replies: when this board is not first on the ID list
 * it answers only after observing the immediately preceding listed ID's valid
 * status packet; absent/corrupt predecessor => this board skips the round to
 * avoid collision. MEASURED LIMIT (Feetech servo firmware 3.46): the next
 * servo starts transmitting ~180 us after the previous reply begins, so if
 * ID 200 is FIRST its checksum byte collides with that early servo reply
 * (3/30 success). Controllers MUST place ID 200 AFTER the servos (middle or
 * last in the list), or list it alone: both are 100% reliable.
 * Broadcast Ping is deliberately silent: only addressed Ping is supported. */
void proto_feed(proto_context *ctx, uint8_t byte, uint32_t now_us);
void proto_poll(proto_context *ctx, uint32_t now_us);
/* Discard partial RX/pending TX after UART overrun or a board-level bus fault. */
void proto_reset_receiver(proto_context *ctx);
/* ~(sum bytes) & 0xFF, the Feetech packet checksum. Exposed for host tests. */
uint8_t proto_checksum(const uint8_t *bytes, uint16_t length);

#endif
