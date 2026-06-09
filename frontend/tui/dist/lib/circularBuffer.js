export class CircularBuffer {
  capacity;
  buf;
  head = 0;
  len = 0;
  constructor(capacity) {
    this.capacity = capacity;
    if (!Number.isInteger(capacity) || capacity <= 0) {
      throw new RangeError(`CircularBuffer capacity must be a positive integer, got ${capacity}`);
    }
    this.buf = new Array(capacity);
  }
  push(item) {
    this.buf[this.head] = item;
    this.head = (this.head + 1) % this.capacity;
    if (this.len < this.capacity) {
      this.len++;
    }
  }
  tail(n = this.len) {
    const take = Math.min(Math.max(0, n), this.len);
    const start = this.len < this.capacity ? 0 : this.head;
    const out = new Array(take);
    for (let i = 0; i < take; i++) {
      out[i] = this.buf[(start + this.len - take + i) % this.capacity];
    }
    return out;
  }
  drain() {
    const out = this.tail();
    this.clear();
    return out;
  }
  clear() {
    this.buf = new Array(this.capacity);
    this.head = 0;
    this.len = 0;
  }
}