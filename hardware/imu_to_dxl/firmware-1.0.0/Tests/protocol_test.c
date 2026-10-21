#include "protocol.h"
#include <stdio.h>
#include <string.h>

static unsigned checks;
static unsigned failures;
#define CHECK(test) do { ++checks; if (!(test)) { ++failures; \
    printf("FAIL line %u: %s\n", (unsigned)__LINE__, #test); } } while (0)

typedef struct {
    proto_context protocol;
    uint8_t registers[320];
    uint8_t output[512];
    uint16_t output_length;
    unsigned sends;
    unsigned writes;
    uint32_t now;
} fixture;

static uint8_t read_regs(void *user, uint16_t address, uint16_t length, uint8_t *out)
{
    fixture *f = (fixture *)user;
    if ((uint32_t)address + length > sizeof(f->registers)) {
        return PROTO_ERR_ACCESS;
    }
    memcpy(out, f->registers + address, length);
    return PROTO_OK;
}

static uint8_t write_regs(void *user, uint16_t address, uint16_t length,
                          const uint8_t *data)
{
    fixture *f = (fixture *)user;
    if ((uint32_t)address + length > sizeof(f->registers)) {
        return PROTO_ERR_ACCESS;
    }
    memcpy(f->registers + address, data, length);
    ++f->writes;
    return PROTO_OK;
}

static void send_bytes(void *user, const uint8_t *packet, uint16_t length)
{
    fixture *f = (fixture *)user;
    CHECK(length <= sizeof(f->output));
    memcpy(f->output, packet, length);
    f->output_length = length;
    ++f->sends;
}

static void init(fixture *f)
{
    unsigned i;
    memset(f, 0, sizeof(*f));
    for (i = 0u; i < sizeof(f->registers); ++i) {
        f->registers[i] = (uint8_t)i;
    }
    proto_init(&f->protocol, read_regs, write_regs, send_bytes, f);
}

/* Test traffic encoder. A status packet is the same framing with instruction
 * byte 0x00 (no error); the protocol under test never calls this encoder. */
static uint16_t packet(uint8_t *out, uint8_t id, uint8_t instruction,
                        const uint8_t *params, uint16_t count)
{
    out[0] = 0xFFu; out[1] = 0xFFu; out[2] = id;
    out[3] = (uint8_t)(count + 2u); out[4] = instruction;
    if (count != 0u) { memcpy(out + 5u, params, count); }
    out[5u + count] = proto_checksum(out + 2u, (uint16_t)(count + 3u));
    return (uint16_t)(count + 6u);
}

static void receive(fixture *f, const uint8_t *data, uint16_t length)
{
    uint16_t i;
    for (i = 0u; i < length; ++i) {
        f->now += 10u;
        proto_feed(&f->protocol, data[i], f->now);
    }
}

static void request(fixture *f, uint8_t id, uint8_t instruction,
                     const uint8_t *params, uint16_t count)
{
    uint8_t wire[512];
    uint16_t length = packet(wire, id, instruction, params, count);
    receive(f, wire, length);
}

static void poll(fixture *f, uint32_t elapsed)
{
    f->now += elapsed;
    proto_poll(&f->protocol, f->now);
}

static void test_checksum_reference(void)
{
    /* Hand-computed: ~(200+2+1) = ~0xCB = 0x34 for an ID-200 empty PING. */
    static const uint8_t ping_sum[] = {200u, 2u, 1u};
    uint8_t wire[6];
    CHECK(proto_checksum(ping_sum, 3u) == 0x34u);
    CHECK(packet(wire, 200u, 1u, 0, 0u) == 6u);
    CHECK(wire[0] == 0xFFu && wire[1] == 0xFFu && wire[2] == 200u);
    CHECK(wire[3] == 2u && wire[4] == 1u && wire[5] == 0x34u);
    /* READ 56/12 to ID 200: request LEN = 2 params + 2 = 4. */
    {
        const uint8_t p[] = {56u, 12u};
        uint8_t frame[8];
        CHECK(packet(frame, 200u, 2u, p, 2u) == 8u);
        CHECK(frame[3] == 4u);
        CHECK(frame[7] == proto_checksum(frame + 2u, 5u));
        CHECK((uint16_t)(200u + 4u + 2u + 56u + 12u) == 274u);
    }
}

static void test_ping_and_read(void)
{
    fixture f;
    const uint8_t block[] = {56u, 12u};
    const uint8_t ident[] = {0u, 10u};
    unsigned i;
    init(&f);
    request(&f, 200, 1, 0, 0);
    CHECK(f.sends == 0u); /* Feed never sends synchronously or from an ISR. */
    poll(&f, 0);
    CHECK(f.sends == 1u && f.output_length == 6u);
    CHECK(f.output[2] == 200u && f.output[3] == 2u && f.output[4] == 0u);
    /* Status checksum: ~(200 + 2 + ERR0) = ~202 = 0x35. */
    CHECK(f.output[5] == 0x35u);
    request(&f, 200, 2, block, sizeof(block));
    poll(&f, 0);
    CHECK(f.sends == 2u && f.output_length == 18u);
    CHECK(f.output[3] == 14u && f.output[4] == 0u);
    for (i = 0u; i < 12u; ++i) { CHECK(f.output[5u + i] == 56u + i); }
    CHECK(f.output[17] == proto_checksum(f.output + 2u, 15u));
    /* Identity 0..9: ver major/minor, endian, model, ID, baud, level. */
    request(&f, 200, 2, ident, sizeof(ident));
    poll(&f, 0);
    CHECK(f.sends == 3u && f.output_length == 16u);
    CHECK(f.output[5] == 1u && f.output[6] == 0u);   /* major, minor */
    CHECK(f.output[7] == 0u);                          /* endian = 0 (little) */
    CHECK(f.output[8] == 0x44u && f.output[9] == 0x4Du); /* model 0x4D44 */
    CHECK(f.output[10] == 200u && f.output[11] == 0u);  /* ID, baud */
    CHECK(f.output[13] == 1u && f.output[14] == 0u);    /* status level, reserved */
    CHECK(f.output[15] == proto_checksum(f.output + 2u, 13u));
    request(&f, 199, 1, 0, 0); poll(&f, 0);
    request(&f, 254, 1, 0, 0); poll(&f, 0); /* Broadcast ping is silent. */
    request(&f, 254, 2, block, sizeof(block)); poll(&f, 0);
    CHECK(f.sends == 3u);
}

static void test_read_limits(void)
{
    fixture f;
    const uint8_t overflow[] = {250u, 12u};
    const uint8_t zero[] = {56u, 0u};
    const uint8_t huge[] = {0u, 129u};
    const uint8_t maximum[] = {0u, 128u};
    const uint8_t short_param[] = {56u};
    init(&f);
    request(&f, 200, 2, overflow, sizeof(overflow)); poll(&f, 0);
    CHECK(f.output[4] == PROTO_ERR_RANGE && f.output_length == 6u);
    request(&f, 200, 2, zero, sizeof(zero)); poll(&f, 0);
    CHECK(f.output[4] == PROTO_ERR_LENGTH);
    request(&f, 200, 2, huge, sizeof(huge)); poll(&f, 0);
    CHECK(f.output[4] == PROTO_ERR_RANGE);
    request(&f, 200, 2, maximum, sizeof(maximum)); poll(&f, 0);
    CHECK(f.output[4] == PROTO_OK && f.output_length == 134u);
    request(&f, 200, 2, short_param, sizeof(short_param)); poll(&f, 0);
    CHECK(f.output[4] == PROTO_ERR_LENGTH);
    /* A read spanning owned and application addresses merges both sources. */
    {
        const uint8_t span[] = {8u, 4u};
        request(&f, 200, 2, span, sizeof(span)); poll(&f, 0);
        CHECK(f.output[4] == PROTO_OK && f.output_length == 10u);
        CHECK(f.output[5] == 1u && f.output[6] == 0u);  /* status level, reserved */
        CHECK(f.output[7] == 10u && f.output[8] == 11u); /* callback addresses */
    }
}

static void test_writes(void)
{
    fixture f;
    const uint8_t marker[] = {84u, 7u};
    const uint8_t identity[] = {5u, 9u};
    const uint8_t broadcast[] = {84u, 8u};
    init(&f);
    request(&f, 200, 3, marker, sizeof(marker)); poll(&f, 0);
    CHECK(f.sends == 1u && f.output[4] == 0u && f.writes == 1u);
    CHECK(f.registers[84] == 7u);
    request(&f, 200, 3, identity, sizeof(identity)); poll(&f, 0);
    CHECK(f.output[4] == PROTO_ERR_ACCESS && f.writes == 1u);
    request(&f, 254, 3, broadcast, sizeof(broadcast)); poll(&f, 0);
    CHECK(f.sends == 2u && f.writes == 2u && f.registers[84] == 8u);
}

static void test_sync_write(void)
{
    fixture f;
    const uint8_t hit[] = {84u, 1u, 1u, 0u, 200u, 9u, 3u, 0u};
    const uint8_t absent[] = {84u, 1u, 1u, 0u, 2u, 0u};
    const uint8_t truncated[] = {84u, 2u, 200u, 1u};
    const uint8_t duplicate[] = {84u, 1u, 200u, 1u, 200u, 0u};
    const uint8_t bad_id[] = {84u, 1u, 255u, 0u, 200u, 9u};
    init(&f);
    request(&f, 254, 0x83u, absent, sizeof(absent)); poll(&f, 0);
    request(&f, 254, 0x83u, truncated, sizeof(truncated)); poll(&f, 0);
    request(&f, 254, 0x83u, duplicate, sizeof(duplicate)); poll(&f, 0);
    request(&f, 254, 0x83u, bad_id, sizeof(bad_id)); poll(&f, 0);
    CHECK(f.writes == 0u && f.sends == 0u);
    CHECK(f.protocol.malformed_packets == 3u); /* truncated/duplicate/bad */
    request(&f, 254, 0x83u, hit, sizeof(hit)); poll(&f, 0);
    CHECK(f.writes == 1u && f.sends == 0u && f.registers[84] == 9u);
}

static void test_sync_read_order(void)
{
    fixture f;
    const uint8_t ours_first[] = {56u, 12u, 200u, 1u, 2u};
    const uint8_t ours_second[] = {56u, 12u, 1u, 200u, 2u};
    const uint8_t absent[] = {56u, 12u, 1u, 2u};
    const uint8_t duplicate[] = {56u, 12u, 200u, 1u, 200u};
    const uint8_t status[] = {0u, 1u, 2u, 3u};
    uint8_t corrupt[64];
    uint16_t n;
    init(&f);
    request(&f, 254, 0x82u, absent, sizeof(absent)); poll(&f, 0);
    request(&f, 200, 0x82u, ours_first, sizeof(ours_first)); poll(&f, 0);
    request(&f, 254, 0x82u, duplicate, sizeof(duplicate)); poll(&f, 0);
    CHECK(f.sends == 0u);
    request(&f, 254, 0x82u, ours_first, sizeof(ours_first)); poll(&f, 0);
    CHECK(f.sends == 1u && f.output_length == 18u);
    /* Listed second: wait for ID 1's status packet. */
    request(&f, 254, 0x82u, ours_second, sizeof(ours_second)); poll(&f, 50u);
    CHECK(f.sends == 1u && f.protocol.pending == 2u);
    request(&f, 2, 0x00u, status, sizeof(status)); poll(&f, 0);
    CHECK(f.sends == 1u); /* An unrelated slave cannot release this turn. */
    n = packet(corrupt, 1, 0x00u, status, sizeof(status));
    corrupt[n - 1u] ^= 1u;
    receive(&f, corrupt, n); poll(&f, 0);
    CHECK(f.sends == 1u); /* A corrupt predecessor status cannot release it. */
    request(&f, 1, 0x00u, status, sizeof(status)); poll(&f, 0);
    CHECK(f.sends == 2u && f.protocol.pending == 0u);
    /* A late status after the transaction window never revives the read. */
    request(&f, 254, 0x82u, ours_second, sizeof(ours_second));
    poll(&f, PROTO_TRANSACTION_TIMEOUT_US);
    request(&f, 1, 0x00u, status, sizeof(status)); poll(&f, 0);
    CHECK(f.sends == 2u);
    /* A new controller broadcast transaction while waiting cancels the round. */
    request(&f, 254, 0x82u, ours_second, sizeof(ours_second));
    request(&f, 254, 0x82u, absent, sizeof(absent));
    request(&f, 1, 0x00u, status, sizeof(status)); poll(&f, 0);
    CHECK(f.sends == 2u);
    request(&f, 254, 0x82u, ours_first, sizeof(ours_first));
    poll(&f, PROTO_REPLY_EXPIRY_US + 1u);
    CHECK(f.sends == 2u); /* Do not inject a stale reply into the next cycle. */
}

static void test_error_recovery(void)
{
    fixture f;
    uint8_t wire[64];
    uint16_t n;
    init(&f);
    n = packet(wire, 200, 1, 0, 0);
    wire[n - 1u] ^= 1u;
    receive(&f, wire, n); poll(&f, 0);
    CHECK(f.sends == 0u && f.protocol.checksum_errors == 1u);
    request(&f, 200, 1, 0, 0); poll(&f, 0);
    CHECK(f.sends == 1u);
    /* A truncated frame is dropped on the inter-byte timeout. */
    f.now += 10u;
    proto_feed(&f.protocol, 0xFFu, f.now);
    f.now += 10u;
    proto_feed(&f.protocol, 0xFFu, f.now);
    f.now += 10u;
    proto_feed(&f.protocol, 200u, f.now);
    poll(&f, 1501u);
    CHECK(f.protocol.receive_timeouts == 1u);
    request(&f, 200, 1, 0, 0); poll(&f, 0);
    CHECK(f.sends == 2u);
    /* Illegal IDs (0, 255) and illegal lengths are rejected, bus recovers. */
    receive(&f, (const uint8_t[]){0xFFu, 0xFFu, 0x00u, 0x02u, 0x01u, 0x00u}, 6u);
    receive(&f, (const uint8_t[]){0xFFu, 0xFFu, 0xFFu, 0x02u, 0x01u, 0x00u}, 6u);
    receive(&f, (const uint8_t[]){0xFFu, 0xFFu, 200u, 0x00u, 0x01u, 0x00u}, 6u);
    receive(&f, (const uint8_t[]){0xFFu, 0xFFu, 200u, 0xFFu, 0x01u, 0x00u}, 6u);
    CHECK(f.protocol.malformed_packets >= 4u);
    request(&f, 200, 1, 0, 0); poll(&f, 0);
    CHECK(f.sends == 3u);
    /* Extra leading FFs are tolerated as header-search noise. */
    proto_feed(&f.protocol, 255u, ++f.now);
    proto_feed(&f.protocol, 255u, ++f.now);
    request(&f, 200, 1, 0, 0); poll(&f, 0);
    CHECK(f.sends == 4u);
}

static void test_wraparound_and_reset(void)
{
    fixture f;
    const uint8_t ours_second[] = {56u, 12u, 1u, 200u};
    init(&f);
    f.now = 0xFFFFFF70u;
    request(&f, 200, 1, 0, 0);
    poll(&f, 20u);
    CHECK(f.sends == 1u); /* Unsigned timestamp wraparound is harmless. */
    request(&f, 200, 1, 0, 0);
    proto_reset_receiver(&f.protocol); poll(&f, 200u);
    CHECK(f.sends == 1u);
    request(&f, 254, 0x82u, ours_second, sizeof(ours_second)); poll(&f, 0);
    CHECK(f.protocol.pending == 2u);
    proto_reset_receiver(&f.protocol); poll(&f, 0);
    CHECK(f.protocol.pending == 0u);
    request(&f, 200, 1, 0, 0); poll(&f, 0);
    CHECK(f.sends == 2u);
}

static void test_capacity_and_noise(void)
{
    struct { unsigned before; fixture f; unsigned after; } guarded;
    uint32_t random = 0x16432478u;
    unsigned i;
    const uint8_t maximum[] = {0u, 128u};
    guarded.before = 0xDEADBEEFu; guarded.after = 0x12345678u;
    init(&guarded.f);
    memset(guarded.f.registers, 255, sizeof(guarded.f.registers));
    request(&guarded.f, 200, 2, maximum, sizeof(maximum)); poll(&guarded.f, 0);
    CHECK(guarded.f.sends == 1u && guarded.f.output_length == 134u);
    for (i = 0u; i < 200000u; ++i) {
        random ^= random << 13; random ^= random >> 17; random ^= random << 5;
        proto_feed(&guarded.f.protocol, (uint8_t)random, ++guarded.f.now);
        if ((i & 127u) == 0u) { poll(&guarded.f, 0); }
    }
    poll(&guarded.f, 2000u);
    request(&guarded.f, 200, 1, 0, 0); poll(&guarded.f, 0);
    CHECK(guarded.f.sends >= 2u);
    CHECK(guarded.before == 0xDEADBEEFu && guarded.after == 0x12345678u);
}

int main(void)
{
    test_checksum_reference();
    test_ping_and_read();
    test_read_limits();
    test_writes();
    test_sync_write();
    test_sync_read_order();
    test_error_recovery();
    test_wraparound_and_reset();
    test_capacity_and_noise();
    printf("Feetech protocol tests: %u checks, %u failures. Context: %u bytes.\n",
           checks, failures, (unsigned)sizeof(proto_context));
    return failures == 0u ? 0 : 1;
}
