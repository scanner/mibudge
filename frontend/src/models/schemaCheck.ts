//
// Compile-time checks that a domain type matches a generated schema
// type.  Model layer.
//
// `Expect<Equal<A, B>>` fails to type-check when `A` and `B` differ,
// so regenerating `api/schema.d.ts` after an enum changes on the
// server breaks the build until the domain union is updated.
//

export type Equal<A, B> =
  (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false;

export type Expect<T extends true> = T;
